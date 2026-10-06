"""Event APIs (LLD section 25.2) including forecast and evidence graph."""

from aeropulse_auth.jwt import TokenClaims
from aeropulse_contracts.event import EventStatus
from fastapi import APIRouter, Depends, HTTPException, Query

from aeropulse_api.deps import get_claims
from aeropulse_api.event_store import EventReader, get_event_reader

router = APIRouter(prefix="/api/v1/events", tags=["events"])


@router.get("")
def list_events(
    _claims: TokenClaims = Depends(get_claims),
    reader: EventReader = Depends(get_event_reader),
    status: str | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1, le=500, description="Max items to return"),
    offset: int = Query(default=0, ge=0, description="Items to skip, oldest-updated first"),
) -> dict:
    """List pollution events from the configured read repository."""
    wanted = None
    if status:
        try:
            wanted = EventStatus(status)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Invalid status") from exc
    page, total = reader.list_events(wanted, limit, offset)
    return {
        "items": [e.model_dump(mode="json") for e in page],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/{event_id}")
def get_event(
    event_id: str,
    _claims: TokenClaims = Depends(get_claims),
    reader: EventReader = Depends(get_event_reader),
) -> dict:
    """Fetch a single event.v1 payload."""
    event = reader.get_event(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail=f"Event {event_id} not found")
    return event.model_dump(mode="json")


@router.get("/{event_id}/evidence")
def get_evidence(
    event_id: str,
    _claims: TokenClaims = Depends(get_claims),
    reader: EventReader = Depends(get_event_reader),
) -> dict:
    """List evidence items for an event."""
    if reader.get_event(event_id) is None:
        raise HTTPException(status_code=404, detail=f"Event {event_id} not found")
    items = reader.get_evidence(event_id)
    return {"items": [e.model_dump(mode="json") for e in items]}


@router.get("/{event_id}/forecast")
def get_forecast(
    event_id: str,
    _claims: TokenClaims = Depends(get_claims),
    reader: EventReader = Depends(get_event_reader),
) -> dict:
    """Return wind-advection forecast.v1 for an event."""
    if reader.get_event(event_id) is None:
        raise HTTPException(status_code=404, detail=f"Event {event_id} not found")
    forecast = reader.get_forecast(event_id)
    if forecast is None:
        raise HTTPException(status_code=404, detail="Forecast not generated")
    payload = forecast.model_dump(mode="json")
    payload["horizon_hours"] = 12
    return payload


@router.get("/{event_id}/graph")
def get_graph(
    event_id: str,
    _claims: TokenClaims = Depends(get_claims),
    reader: EventReader = Depends(get_event_reader),
) -> dict:
    """Return Timescale-shaped evidence lineage (graph.v1), not Arango."""
    if reader.get_event(event_id) is None:
        raise HTTPException(status_code=404, detail=f"Event {event_id} not found")
    graph = reader.get_graph(event_id)
    if graph is None:
        raise HTTPException(status_code=404, detail="Graph not generated")
    return graph.model_dump(mode="json")
