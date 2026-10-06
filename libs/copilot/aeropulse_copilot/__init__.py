"""Gemini-grounded copilot for AeroPulse.

The LLM boundary lives here, deliberately outside ``libs/intelligence``: the
event path stays deterministic (AGENTS.md), and the copilot only explains
what that path already computed.
"""

from aeropulse_copilot.gemini import GeminiCopilot, GeminiUnavailableError
from aeropulse_copilot.grounding import GroundingResult, validate_answer
from aeropulse_copilot.service import CopilotAnswer, CopilotService
from aeropulse_copilot.tools import TOOLS, ToolContext, ToolLedger, cpcb_band, describe_tools

__all__ = [
    "TOOLS",
    "CopilotAnswer",
    "CopilotService",
    "GeminiCopilot",
    "GeminiUnavailableError",
    "GroundingResult",
    "ToolContext",
    "ToolLedger",
    "cpcb_band",
    "describe_tools",
    "validate_answer",
]
