"""Gemini client and the tool-calling loop.

Automatic function calling is deliberately disabled. The SDK can execute
tools itself, but then the results never surface to us and the grounding
validator has nothing to check against. Driving the loop by hand costs a few
lines and is what makes "every number came from a tool" verifiable rather
than aspirational.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aeropulse_observability.logging import get_logger

from aeropulse_copilot.tools import TOOLS, ToolContext, ToolLedger, describe_tools

logger = get_logger("aeropulse.copilot.gemini")

_PROMPT_DIR = Path(__file__).resolve().parent / "prompts"

#: Bound on tool round-trips for one question. Reached only by a model stuck
#: in a loop; the worked examples need at most three.
MAX_TOOL_ROUNDS = 6


def system_prompt(version: str = "v1") -> str:
    """Load the versioned system prompt."""
    return (_PROMPT_DIR / f"system_{version}.md").read_text(encoding="utf-8")


class GeminiUnavailableError(RuntimeError):
    """Raised when the Gemini SDK or credential is absent."""


@dataclass
class GeminiAnswer:
    """One completed model turn.

    Attributes:
        text: The model's prose.
        ledger: Every tool call made to produce it.
        rounds: Tool round-trips used.
        model: Model id that answered.
    """

    text: str
    ledger: ToolLedger
    rounds: int
    model: str


class GeminiCopilot:
    """Answers questions by calling AeroPulse tools through Gemini.

    Args:
        api_key: Gemini API key. Absent means this client cannot be used and
            the caller must fall back to deterministic retrieval.
        model: Model id. Configurable because the right Flash generation
            changes faster than this code does.
        client: Pre-built ``google.genai.Client``, for tests.
        prompt_version: Which versioned system prompt to load.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "gemini-3.8-flash",
        client: Any | None = None,
        prompt_version: str = "v1",
    ) -> None:
        self.model = model
        self.prompt_version = prompt_version
        self._client = client
        self._api_key = api_key

    @property
    def available(self) -> bool:
        """Whether this client can actually answer."""
        return self._client is not None or bool(self._api_key)

    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        if not self._api_key:
            raise GeminiUnavailableError("AEROPULSE_GEMINI_API_KEY is not set")
        try:
            from google import genai
        except ImportError as exc:  # pragma: no cover - depends on optional extra
            raise GeminiUnavailableError(
                "google-genai is not installed; add the 'gemini' extra"
            ) from exc
        self._client = genai.Client(api_key=self._api_key)
        return self._client

    def _config(self, extra_instruction: str | None = None) -> Any:
        from google.genai import types

        instruction = system_prompt(self.prompt_version)
        if extra_instruction:
            instruction = f"{instruction}\n\n## Correction\n\n{extra_instruction}"
        declarations = [types.FunctionDeclaration(**decl) for decl in describe_tools()]
        return types.GenerateContentConfig(
            system_instruction=instruction,
            tools=[types.Tool(function_declarations=declarations)],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            temperature=0.2,
        )

    def answer(
        self,
        question: str,
        ctx: ToolContext,
        *,
        history: list[dict[str, str]] | None = None,
        extra_instruction: str | None = None,
    ) -> GeminiAnswer:
        """Answer one question, executing tool calls as the model requests them.

        Args:
            question: The user's question.
            ctx: Readers the tools resolve data through.
            history: Prior turns as ``{"role": ..., "text": ...}``.
            extra_instruction: Appended to the system prompt, used to correct
                a failed grounding attempt.

        Returns:
            The model's answer and the ledger of tool calls behind it.

        Raises:
            GeminiUnavailableError: No SDK or no credential.
        """
        from google.genai import types

        client = self._ensure_client()
        ledger = ToolLedger()
        contents: list[Any] = []
        for turn in history or []:
            role = "model" if turn.get("role") == "assistant" else "user"
            contents.append(types.Content(role=role, parts=[types.Part(text=turn.get("text", ""))]))
        contents.append(types.Content(role="user", parts=[types.Part(text=question)]))

        config = self._config(extra_instruction)
        rounds = 0
        while rounds < MAX_TOOL_ROUNDS:
            response = client.models.generate_content(
                model=self.model, contents=contents, config=config
            )
            calls = getattr(response, "function_calls", None)
            if not calls:
                return GeminiAnswer(
                    text=(getattr(response, "text", "") or "").strip(),
                    ledger=ledger,
                    rounds=rounds,
                    model=self.model,
                )

            rounds += 1
            contents.append(_model_turn(response, types))
            parts = []
            for call in calls:
                name = getattr(call, "name", "")
                args = dict(getattr(call, "args", {}) or {})
                result = self._invoke(name, args, ctx)
                ledger.record(name, args, result)
                parts.append(
                    types.Part.from_function_response(name=name, response={"result": result})
                )
            contents.append(types.Content(role="user", parts=parts))

        logger.warning("copilot.tool_rounds_exhausted", question=question[:120])
        return GeminiAnswer(
            text=(
                "I could not complete that lookup. Try asking about one place or one "
                "event at a time."
            ),
            ledger=ledger,
            rounds=rounds,
            model=self.model,
        )

    def _invoke(self, name: str, args: dict[str, Any], ctx: ToolContext) -> Any:
        """Run one tool, converting any failure into a result the model can read."""
        tool = TOOLS.get(name)
        if tool is None:
            return {"status": "unknown_tool", "name": name}
        try:
            return tool(**args, ctx=ctx)
        except TypeError as exc:
            return {"status": "bad_arguments", "name": name, "detail": str(exc)}
        except Exception as exc:
            logger.exception("copilot.tool_failed", tool=name)
            return {"status": "error", "name": name, "detail": str(exc)}


def _model_turn(response: Any, types: Any) -> Any:
    """Rebuild the model's turn so the tool results attach to the right call."""
    candidates = getattr(response, "candidates", None) or []
    if candidates:
        content = getattr(candidates[0], "content", None)
        if content is not None:
            return content
    return types.Content(role="model", parts=[])
