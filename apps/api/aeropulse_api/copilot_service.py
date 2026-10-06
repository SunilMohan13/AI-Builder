"""Wire the copilot's tool layer to the same readers the REST API serves.

The previous copilot read ``event_store.current_store()`` unconditionally, so
it could only ever see the in-memory demo seed — never a worker-produced
event, even with Timescale populated. Building its tool context from the same
dependency-injected readers the other routes use is what puts the copilot on
live data.
"""

from __future__ import annotations

from functools import lru_cache

from aeropulse_common.settings import get_settings
from aeropulse_copilot import CopilotService, GeminiCopilot, ToolContext
from aeropulse_intelligence.copilot import query_store

from aeropulse_api.hazard_store import hazard_cells, peak_forecasts


def build_tool_context(grid_reader, map_reader, event_reader) -> ToolContext:
    """Assemble the tool context for one request.

    Args:
        grid_reader: Reader from ``get_grid_reader``.
        map_reader: Reader from ``get_map_reader``.
        event_reader: Reader from ``get_event_reader``.

    Returns:
        A context whose tools read exactly what the REST endpoints read.
    """
    return ToolContext(
        grid=grid_reader,
        map=map_reader,
        events=event_reader,
        hazard_cells=hazard_cells,
        peak_forecasts=peak_forecasts,
    )


def _deterministic_fallback(question: str, ctx: ToolContext | None = None):
    """Pre-Gemini behaviour, kept as the degradation path.

    Retrieval over the same event reader the REST routes use. Narrow, but it
    never invents a number, which is the property that matters when the model
    is unavailable.
    """
    events = ctx.events if ctx is not None else None
    if events is None:
        from aeropulse_intelligence.engine import EventStore

        events = EventStore()
    return query_store(events, question)


@lru_cache(maxsize=1)
def get_copilot_service() -> CopilotService:
    """Return the process-wide copilot service.

    Cached because constructing the Gemini client is not free and its
    configuration cannot change within a process.
    """
    settings = get_settings()
    secret = settings.gemini_api_key
    api_key = secret.get_secret_value() if secret is not None else None
    gemini = (
        GeminiCopilot(
            api_key=api_key,
            model=settings.gemini_model,
            prompt_version=settings.copilot_prompt_version,
        )
        if api_key
        else None
    )
    return CopilotService(gemini, fallback=_deterministic_fallback)
