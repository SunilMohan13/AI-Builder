"""Event read repositories for the API.

The in-memory store remains the test double. Deployments with
``AEROPULSE_DATABASE_URL`` read the worker's persisted Timescale state.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any, Protocol

from aeropulse_common.settings import get_settings
from aeropulse_contracts.event import EventEvidence, EventStatus, PollutionEvent
from aeropulse_contracts.forecast import ForecastResult, GridCellForecast
from aeropulse_contracts.lineage import EvidenceGraph, LineageEdge, LineageVertex
from aeropulse_intelligence.engine import EventStore
from fastapi import HTTPException

EVENT_STORE = EventStore()


class EventReader(Protocol):
    """Read-side contract shared by Timescale and the in-memory test double."""

    def list_events(
        self, status: EventStatus | None, limit: int | None, offset: int
    ) -> tuple[list[PollutionEvent], int]: ...

    def get_event(self, event_id: str) -> PollutionEvent | None: ...

    def get_evidence(self, event_id: str) -> list[EventEvidence]: ...

    def get_forecast(self, event_id: str) -> ForecastResult | None: ...

    def get_graph(self, event_id: str) -> EvidenceGraph | None: ...


class InMemoryEventReader:
    """Read the process-local store used by unit tests and DB-free development."""

    def list_events(
        self, status: EventStatus | None, limit: int | None, offset: int
    ) -> tuple[list[PollutionEvent], int]:
        items = list(EVENT_STORE.events.values())
        if status is not None:
            items = [event for event in items if event.status is status]
        items.sort(key=lambda event: event.updated_at, reverse=True)
        total = len(items)
        return (items[offset : offset + limit] if limit is not None else items[offset:], total)

    def get_event(self, event_id: str) -> PollutionEvent | None:
        return EVENT_STORE.events.get(event_id)

    def get_evidence(self, event_id: str) -> list[EventEvidence]:
        return EVENT_STORE.evidence.get(event_id, [])

    def get_forecast(self, event_id: str) -> ForecastResult | None:
        return EVENT_STORE.forecasts.get(event_id)

    def get_graph(self, event_id: str) -> EvidenceGraph | None:
        return EVENT_STORE.graphs.get(event_id)


class TimescaleEventReader:
    """Read worker-persisted intelligence from one request-scoped connection."""

    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def list_events(
        self, status: EventStatus | None, limit: int | None, offset: int
    ) -> tuple[list[PollutionEvent], int]:
        where = "WHERE status = %s" if status is not None else ""
        params: list[Any] = [status.value] if status is not None else []
        with self.connection.cursor() as cursor:
            cursor.execute(f"SELECT count(*) FROM pollution_event {where}", params)
            total = int(cursor.fetchone()[0])
            sql = f"SELECT payload FROM pollution_event {where} ORDER BY updated_at DESC OFFSET %s"
            query_params = [*params, offset]
            if limit is not None:
                sql += " LIMIT %s"
                query_params.append(limit)
            cursor.execute(sql, query_params)
            items = [PollutionEvent.model_validate(row[0]) for row in cursor.fetchall()]
        return items, total

    def get_event(self, event_id: str) -> PollutionEvent | None:
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT payload FROM pollution_event WHERE event_id = %s", (event_id,))
            row = cursor.fetchone()
        return PollutionEvent.model_validate(row[0]) if row else None

    def get_evidence(self, event_id: str) -> list[EventEvidence]:
        sql = """
        SELECT evidence_id, evidence_type, observation_id, grid_id, summary,
               quality_score, created_at
        FROM event_evidence WHERE event_id = %s ORDER BY created_at, evidence_id
        """
        with self.connection.cursor() as cursor:
            cursor.execute(sql, (event_id,))
            return [
                EventEvidence(
                    evidence_id=row[0],
                    evidence_type=row[1],
                    observation_id=row[2],
                    grid_id=row[3],
                    summary=row[4],
                    quality_score=row[5],
                    created_at=row[6],
                )
                for row in cursor.fetchall()
            ]

    def get_forecast(self, event_id: str) -> ForecastResult | None:
        sql = """
        SELECT time, origin_grid_id, grid_id, horizon_hours, pm25, confidence,
               model_version, cams_applied
        FROM forecast_value
        WHERE event_id = %s
          AND time = (SELECT max(time) FROM forecast_value WHERE event_id = %s)
        ORDER BY horizon_hours
        """
        with self.connection.cursor() as cursor:
            cursor.execute(sql, (event_id, event_id))
            rows = cursor.fetchall()
        if not rows:
            return None
        return ForecastResult(
            event_id=event_id,
            origin_grid_id=rows[0][1],
            generated_at=rows[0][0],
            cams_applied=rows[0][7],
            model_version=rows[0][6],
            horizons=sorted({row[3] for row in rows if row[3] > 0}),
            grid_predictions=[
                GridCellForecast(grid_id=row[2], pm25=row[4], confidence=row[5]) for row in rows
            ],
        )

    def get_graph(self, event_id: str) -> EvidenceGraph | None:
        sql = """
        SELECT edge_id, edge_type, from_id, to_id, confidence, evidence_ids,
               model_version, created_at
        FROM evidence_edge
        WHERE event_id = %s
          AND created_at = (SELECT max(created_at) FROM evidence_edge WHERE event_id = %s)
        ORDER BY edge_id
        """
        with self.connection.cursor() as cursor:
            cursor.execute(sql, (event_id, event_id))
            rows = cursor.fetchall()
        if not rows:
            return None
        edges = [
            LineageEdge(
                edge_id=row[0],
                edge_type=row[1],
                from_id=row[2],
                to_id=row[3],
                confidence=row[4],
                evidence_ids=row[5] or [],
                model_version=row[6],
                created_at=row[7],
            )
            for row in rows
        ]
        vertex_ids = sorted({value for edge in edges for value in (edge.from_id, edge.to_id)})
        return EvidenceGraph(
            event_id=event_id,
            vertices=[LineageVertex(id=value, type=_vertex_type(value)) for value in vertex_ids],
            edges=edges,
        )


def _vertex_type(value: str) -> str:
    prefix = value.split(":", 1)[0].split("_", 1)[0]
    return {
        "event": "PollutionEvent",
        "evidence": "Evidence",
        "feature": "FeatureVersion",
        "evt": "event",
        "evd": "evidence",
        "obs": "observation",
        "grid": "GridCell",
        "model": "ModelVersion",
    }.get(prefix, "entity")


class ReplayFallbackEventReader:
    """Timescale when it has events; otherwise the in-memory Punjab replay.

    Compose always sets ``AEROPULSE_DATABASE_URL``, so the worker's empty
    ``pollution_event`` table would 404 ``EVT-1024`` until ingest persists a
    row. Falling back only when the table is empty keeps a later worker
    episode authoritative.
    """

    def __init__(self, primary: EventReader, fallback: EventReader) -> None:
        self.primary = primary
        self.fallback = fallback
        self._use_fallback: bool | None = None

    def _source(self) -> EventReader:
        if self._use_fallback is None:
            _, total = self.primary.list_events(None, 1, 0)
            self._use_fallback = total == 0
        return self.fallback if self._use_fallback else self.primary

    def list_events(
        self, status: EventStatus | None, limit: int | None, offset: int
    ) -> tuple[list[PollutionEvent], int]:
        return self._source().list_events(status, limit, offset)

    def get_event(self, event_id: str) -> PollutionEvent | None:
        return self._source().get_event(event_id)

    def get_evidence(self, event_id: str) -> list[EventEvidence]:
        return self._source().get_evidence(event_id)

    def get_forecast(self, event_id: str) -> ForecastResult | None:
        return self._source().get_forecast(event_id)

    def get_graph(self, event_id: str) -> EvidenceGraph | None:
        return self._source().get_graph(event_id)


def get_event_reader() -> Generator[EventReader, None, None]:
    """Provide a Timescale reader when configured, otherwise the in-memory test double."""
    database_url = get_settings().database_url
    if not database_url:
        yield InMemoryEventReader()
        return
    try:
        import psycopg

        connection = psycopg.connect(database_url)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Event database unavailable") from exc
    try:
        yield ReplayFallbackEventReader(TimescaleEventReader(connection), InMemoryEventReader())
    finally:
        connection.close()


def reset_event_store() -> EventStore:
    """Replace the process store (tests)."""
    global EVENT_STORE
    EVENT_STORE = EventStore()
    return EVENT_STORE


def current_store() -> EventStore:
    """Return the process store. Call this at request time — tests replace it."""
    return EVENT_STORE
