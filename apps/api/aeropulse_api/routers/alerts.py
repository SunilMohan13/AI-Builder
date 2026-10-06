"""Alert listing (LLD section 29). Delivery adapters are not implemented."""

from typing import Annotated

from aeropulse_auth.jwt import TokenClaims
from fastapi import APIRouter, Depends, Query

from aeropulse_api.alert_store import AlertReader, get_alert_reader
from aeropulse_api.deps import get_claims

router = APIRouter(prefix="/api/v1/alerts", tags=["alerts"])


@router.get("")
def list_alerts(
    _claims: Annotated[TokenClaims, Depends(get_claims)],
    reader: Annotated[AlertReader, Depends(get_alert_reader)],
    limit: Annotated[int | None, Query(ge=1, le=500)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    """List alerts generated from HIGH/CRITICAL events, newest first.

    Reads persisted alerts when Timescale has them and falls back to the
    seeded in-memory store otherwise. It previously read the API's own
    in-process store unconditionally, which nothing populates — so this
    endpoint returned an empty list in every deployment.

    Args:
        _claims: Authenticated caller.
        reader: Request-scoped alert reader.
        limit: Maximum alerts to return. Omitting it returns all of them.
        offset: Alerts to skip.

    Returns:
        ``items``/``total``/``limit``/``offset``, matching the convention the
        other collection endpoints follow.
    """
    alerts, total = reader.list_alerts(limit, offset)
    return {
        "items": [a.model_dump(mode="json") for a in alerts],
        "total": total,
        "limit": limit,
        "offset": offset,
    }
