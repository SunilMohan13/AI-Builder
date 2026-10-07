"""Pub/Sub push endpoint for Cloud Storage ``OBJECT_FINALIZE`` notifications (LLD APAC 9.1).

Cloud Run requires an authenticated invoker; the push subscription signs its
requests with a service-account OIDC token, so the push route does no auth
itself. A failure returns 500 so Pub/Sub retries and, after the
subscription's attempt limit, moves the message to the dead-letter topic.

Moderation (LLD 9.6) is the one other route. The API forwards the operator's
own bearer token, so the role check here is on the person, not the API.
"""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Mapping
from typing import Annotated, Any, Literal

from aeropulse_auth.jwt import Role, TokenClaims, decode_token, require_roles
from aeropulse_common.errors import AuthError
from aeropulse_contracts.citizen import VisualClass
from aeropulse_observability import get_logger
from aeropulse_storage import report_id_from_incoming
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel

from aeropulse_citizen_analyzer.analyzer import CitizenAnalyzer, ReportNotFoundError

log = get_logger("aeropulse.citizen.push")

MODERATOR_ROLES = (Role.OPERATOR, Role.AUTHORITY, Role.ADMIN)


class ModerationBody(BaseModel):
    model_config = {"extra": "forbid"}

    action: Literal["accept", "reject", "set_class"]
    visual_class: VisualClass | None = None


def moderator(authorization: Annotated[str | None, Header()] = None) -> TokenClaims:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    try:
        claims = decode_token(authorization.split(" ", 1)[1])
        require_roles(claims, *MODERATOR_ROLES)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return claims


def object_name(envelope: Mapping[str, Any]) -> str | None:
    """The object name from a push envelope: attributes first, then the JSON data."""
    message = envelope.get("message")
    if not isinstance(message, Mapping):
        return None
    attributes = message.get("attributes")
    if isinstance(attributes, Mapping):
        name = attributes.get("objectId")
        if isinstance(name, str) and name:
            return name
    data = message.get("data")
    if not isinstance(data, str):
        return None
    try:
        payload = json.loads(base64.b64decode(data, validate=True))
    except (binascii.Error, ValueError):
        return None
    name = payload.get("name") if isinstance(payload, Mapping) else None
    return name if isinstance(name, str) and name else None


def create_app(analyzer: CitizenAnalyzer) -> FastAPI:
    app = FastAPI(title="AeroPulse citizen analyzer", docs_url=None, redoc_url=None)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok", "observer": analyzer.observer.version}

    @app.post("/pubsub/push")
    async def push(request: Request) -> dict[str, str | None]:
        try:
            envelope = await request.json()
        except ValueError:
            log.warning("citizen.push_bad_envelope")
            return {"status": "ignored", "reason": "not_json"}
        name = object_name(envelope) if isinstance(envelope, Mapping) else None
        report_id = report_id_from_incoming(name) if name else None
        if report_id is None:
            return {"status": "ignored", "reason": "not_an_incoming_upload"}
        try:
            outcome = analyzer.analyze(report_id)
        except ReportNotFoundError:
            log.warning("citizen.push_unknown_report", report_id=report_id)
            return {"status": "ignored", "reason": "unknown_report"}
        except Exception as exc:
            log.exception("citizen.push_failed", report_id=report_id)
            raise HTTPException(status_code=500, detail="analysis failed; will retry") from exc
        decision = outcome.doc.analysis.decision if outcome.doc.analysis else None
        return {"status": "analyzed", "report_id": report_id, "decision": decision}

    @app.post("/reports/{report_id}/moderation")
    def moderation(
        report_id: str,
        body: ModerationBody,
        claims: Annotated[TokenClaims, Depends(moderator)],
    ) -> dict[str, Any]:
        if body.action == "set_class" and body.visual_class is None:
            raise HTTPException(status_code=422, detail="set_class needs visual_class")
        try:
            outcome = analyzer.moderate(
                report_id, action=body.action, visual_class=body.visual_class
            )
        except ReportNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"Report {report_id} not found") from exc
        log.info("citizen.moderated", report_id=report_id, action=body.action, moderator=claims.sub)
        analysis = outcome.doc.analysis
        return {
            "report_id": report_id,
            "moderation": outcome.doc.moderation,
            "moderated_class": outcome.doc.moderated_class,
            "decision": analysis.decision if analysis else None,
            "plume_id": analysis.plume_id if analysis else None,
            "incident_id": analysis.incident_id if analysis else None,
            "alert_id": outcome.alert.alert_id if outcome.alert else None,
        }

    return app
