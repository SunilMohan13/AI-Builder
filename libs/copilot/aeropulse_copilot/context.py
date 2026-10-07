"""What tools read through, and the ledger of what they returned."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from aeropulse_contracts.event import EventStatus
from aeropulse_contracts.plume import Plume
from aeropulse_contracts.snapshot import RegionSnapshot
from aeropulse_intelligence.plume.outputs import Place as RegionPlace
from aeropulse_regions import RegionCatalog

#: A cell whose newest observation is older than this is reported as stale
#: rather than presented as current conditions.
DEFAULT_STALE_AFTER_MINUTES = 90


class GridReaderLike(Protocol):
    """The subset of the API's grid reader the tools need."""

    def latest_feature(self, grid_id: str) -> Any: ...


class MapReaderLike(Protocol):
    """The subset of the API's map reader the tools need."""

    def air_quality(self, bbox: list[float] | None, limit: int) -> list[dict]: ...

    def fire(self, bbox: list[float] | None, limit: int) -> list[dict]: ...

    def weather(self, bbox: list[float] | None, limit: int) -> list[dict]: ...


class EventReaderLike(Protocol):
    """The subset of the API's event reader the tools need."""

    def list_events(
        self, status: EventStatus | None, limit: int, offset: int
    ) -> tuple[list[Any], int]: ...

    def get_event(self, event_id: str) -> Any: ...

    def get_evidence(self, event_id: str) -> list[Any]: ...


@dataclass(frozen=True)
class SeriesPoint:
    """One stored PM2.5 observation, as the trend tools see it."""

    grid_id: str | None
    lat: float
    lon: float
    observed_at: datetime
    value: float
    source_id: str
    provenance_class: str | None


class RegionData(Protocol):
    """Region packs, snapshots, plumes and history, behind one seam.

    The API builds this from its storage; tests build it from a cycle run.
    Every method returns stored output only and never computes a new value.
    """

    @property
    def catalog(self) -> RegionCatalog: ...

    def snapshot(self, region_id: str) -> RegionSnapshot | None: ...

    def plume(self, region_id: str, plume_id: str) -> Plume | None: ...

    def places(self, region_id: str) -> Sequence[RegionPlace]: ...

    def pm25_series(self, region_id: str, start: datetime, end: datetime) -> list[SeriesPoint]: ...

    def citizen_reports(
        self, region_id: str, start: datetime, end: datetime
    ) -> list[dict[str, Any]]: ...


@dataclass
class ToolContext:
    """Readers and settings the tools resolve data through.

    Holding these rather than importing module-level singletons is what lets
    the copilot read exactly the same live data the REST API serves.
    ``regions`` is the snapshot-backed path; ``grid``/``map``/``events`` are
    the legacy ``in-north`` readers used when no snapshot exists.
    """

    grid: GridReaderLike | None = None
    map: MapReaderLike | None = None
    events: EventReaderLike | None = None
    hazard_cells: Any = None
    peak_forecasts: Any = None
    regions: RegionData | None = None
    region_id: str | None = None
    now: Callable[[], datetime] | None = None
    stale_after_minutes: int = DEFAULT_STALE_AFTER_MINUTES

    def clock(self) -> datetime:
        """Current time, injectable for deterministic tests."""
        return self.now() if self.now is not None else datetime.now(UTC)


@dataclass
class ToolCall:
    """One tool invocation and what it returned.

    Attributes:
        name: Tool name.
        arguments: Arguments the model supplied.
        result: The returned payload, recorded verbatim for grounding.
    """

    name: str
    arguments: dict[str, Any]
    result: Any


@dataclass
class ToolLedger:
    """Every tool call made while answering one question."""

    calls: list[ToolCall] = field(default_factory=list)

    def record(self, name: str, arguments: dict[str, Any], result: Any) -> None:
        """Append a call and its result."""
        self.calls.append(ToolCall(name=name, arguments=dict(arguments), result=result))

    def sources(self) -> list[dict[str, str]]:
        """Distinct evidence citations across every call."""
        seen: dict[tuple[str, str], dict[str, str]] = {}
        for call in self.calls:
            for citation in citations(call.result):
                key = (citation.get("source", ""), citation.get("time", ""))
                seen.setdefault(key, citation)
        return list(seen.values())


def citations(payload: Any) -> list[dict[str, str]]:
    """Every ``{source, observed_at}`` pair anywhere in a tool result."""
    found: list[dict[str, str]] = []
    if isinstance(payload, dict):
        if "source" in payload and "observed_at" in payload:
            found.append(
                {"source": str(payload["source"]), "time": str(payload["observed_at"] or "")}
            )
        for value in payload.values():
            found.extend(citations(value))
    elif isinstance(payload, list):
        for item in payload:
            found.extend(citations(item))
    return found


def staleness(observed_at: datetime | None, ctx: ToolContext) -> dict[str, Any]:
    """``observed_at``, its age against the context clock, and whether it is stale."""
    if observed_at is None:
        return {"observed_at": None, "age_minutes": None, "stale": True}
    now = ctx.clock()
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=UTC)
    age = (now - observed_at).total_seconds() / 60.0
    return {
        "observed_at": observed_at.isoformat(),
        "age_minutes": round(age, 1),
        "stale": age > ctx.stale_after_minutes,
    }


def iso(value: Any) -> str | None:
    """ISO-8601 text for a datetime, ``str`` for anything else, ``None`` kept."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)
