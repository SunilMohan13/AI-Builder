"""Citizen Smoke Intelligence APIs (LLD APAC 9.10).

The API creates the report document and takes the upload; everything that
looks at the photo happens in the citizen analyzer. A report is an AI visual
observation checked against the environment, never a measurement, and it
never changes an event, a prediction or a label.

Abuse controls: per-reporter and per-IP hourly limits from
``config/citizen.yaml``; the reporter is stored only as an HMAC of their
token subject; the claimed point must fall inside an onboarded region.
Public views carry rounded coordinates and no notes.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
from collections import defaultdict, deque
from datetime import timedelta
from time import monotonic
from typing import Annotated, Any

from aeropulse_auth.jwt import Role, TokenClaims
from aeropulse_common.settings import DEV_ENVIRONMENTS, Settings
from aeropulse_contracts.citizen import CitizenReportDocument, VisualClass
from aeropulse_observability.logging import get_logger
from aeropulse_storage import (
    ObjectNotFoundError,
    PreconditionFailedError,
    StorageError,
    batch_id,
    citizen_row,
)
from aeropulse_vision.sanitize import sniff
from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from pydantic import AwareDatetime, BaseModel, Field

from aeropulse_api.citizen_client import (
    AnalyzerClient,
    AnalyzerUnavailableError,
    get_analyzer_client,
)
from aeropulse_api.deps import get_claims, require
from aeropulse_api.platform import ApiPlatform, get_platform, page, region_id_param

router = APIRouter(prefix="/api/v1/citizen", tags=["citizen"])
log = get_logger("aeropulse.api.citizen")

REPORTER_ROLES = (Role.CITIZEN, Role.VIEWER, Role.ADMIN)
MODERATOR_ROLES = (Role.OPERATOR, Role.AUTHORITY, Role.ADMIN)
#: Roles that see operator-only reports, exact locations and the photo.
OPERATOR_VIEW_ROLES = frozenset({Role.OPERATOR, Role.AUTHORITY, Role.ADMIN, Role.ANALYST})
#: Default lookback of the report list.
LIST_DAYS = 30

_DEV_SALT = secrets.token_bytes(32)
_windows: defaultdict[str, deque[float]] = defaultdict(deque)
_lock = threading.Lock()


def reset_citizen_limits() -> None:
    with _lock:
        _windows.clear()


def reporter_hash(settings: Settings, subject: str) -> str:
    salt = settings.citizen_reporter_salt
    if salt is not None:
        key = salt.get_secret_value().encode()
    elif settings.environment.lower() in DEV_ENVIRONMENTS:
        key = _DEV_SALT
    else:
        raise HTTPException(
            status_code=503, detail="AEROPULSE_CITIZEN_REPORTER_SALT is not configured"
        )
    return hmac.new(key, subject.encode(), hashlib.sha256).hexdigest()


def _limit(key: str, per_hour: int) -> None:
    now = monotonic()
    with _lock:
        window = _windows[key]
        while window and now - window[0] >= 3600:
            window.popleft()
        if len(window) >= per_hour:
            raise HTTPException(status_code=429, detail="Citizen report rate limit exceeded")
        window.append(now)


def _is_operator(claims: TokenClaims) -> bool:
    return any(role in OPERATOR_VIEW_ROLES for role in claims.roles)


def _record(platform: ApiPlatform, doc: CitizenReportDocument, stage: str) -> None:
    row = citizen_row(
        doc,
        recorded_at=platform.clock(),
        round_decimals=platform.citizen.decision.public_round_decimals,
    )
    platform.storage.analytics.load(
        "citizen.reports", [row], batch_id=batch_id(f"{doc.report_id}_{stage}", [row])
    )


def _view(platform: ApiPlatform, doc: CitizenReportDocument, *, private: bool) -> dict[str, Any]:
    decimals = platform.citizen.decision.public_round_decimals
    body = doc.model_dump(mode="json", exclude={"reporter_hash", "incoming_key", "sanitized_key"})
    analysis = doc.analysis
    observation = analysis.observation if analysis else None
    body["visual_class"] = doc.moderated_class or (
        observation.visual_class if observation else None
    )
    body["visual_class_provenance"] = (
        "citizen" if doc.moderated_class else ("ai_observation" if observation else None)
    )
    body["has_media"] = doc.sanitized_key is not None
    if not private:
        body["claimed_lat"] = round(doc.claimed_lat, decimals)
        body["claimed_lon"] = round(doc.claimed_lon, decimals)
        body.pop("notes", None)
        body.pop("device_accuracy_m", None)
        body["location_rounded_to_decimals"] = decimals
    return body


def _load(platform: ApiPlatform, report_id: str) -> CitizenReportDocument:
    try:
        found = platform.storage.citizen.get(report_id)
    except StorageError as exc:
        raise HTTPException(status_code=404, detail=f"Report {report_id} not found") from exc
    if found is None:
        raise HTTPException(status_code=404, detail=f"Report {report_id} not found")
    return found[0]


def _operators_only(doc: CitizenReportDocument) -> bool:
    decision = doc.analysis.decision if doc.analysis else None
    return doc.moderation == "rejected" or decision == "stored_operators_only"


def _access(
    platform: ApiPlatform, doc: CitizenReportDocument, claims: TokenClaims
) -> tuple[bool, bool]:
    """(is the reporter, may see the private view)."""
    own = hmac.compare_digest(doc.reporter_hash, reporter_hash(platform.settings, claims.sub))
    return own, own or _is_operator(claims)


class CreateReport(BaseModel):
    model_config = {"extra": "forbid"}

    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    region_id: str | None = None
    observation_type: str = Field(default="photo", pattern=r"^[a-z_]{1,32}$")
    notes: str | None = Field(default=None, max_length=1000)
    device_accuracy_m: float | None = Field(default=None, ge=0)
    client_captured_at: AwareDatetime | None = None
    content_type: str = "image/jpeg"


def _upload_instruction(
    platform: ApiPlatform, doc: CitizenReportDocument, content_type: str
) -> dict[str, Any]:
    upload = platform.citizen.upload
    multipart = {
        "method": "POST",
        "url": f"/api/v1/citizen/reports/{doc.report_id}/media",
        "encoding": "multipart/form-data",
        "field": "file",
        "max_bytes": upload.max_bytes,
    }
    if platform.storage.platform != "gcp" or doc.incoming_key is None:
        return multipart
    try:
        url = platform.storage.objects["citizen"].signed_upload_url(
            doc.incoming_key,
            content_type=content_type,
            max_bytes=upload.max_bytes,
            ttl_s=upload.signed_url_ttl_seconds,
        )
    except StorageError as exc:
        log.warning("citizen.signed_url_failed", report_id=doc.report_id, error=str(exc))
        return multipart
    return {
        "method": "PUT",
        "url": url,
        "headers": {"Content-Type": content_type},
        "expires_in_s": upload.signed_url_ttl_seconds,
        "max_bytes": upload.max_bytes,
    }


@router.post("/reports", status_code=201)
def create_report(
    body: CreateReport,
    request: Request,
    claims: Annotated[TokenClaims, Depends(require(*REPORTER_ROLES))],
    platform: Annotated[ApiPlatform, Depends(get_platform)],
) -> dict[str, Any]:
    """Create a report and say where to upload its photo."""
    upload = platform.citizen.upload
    if body.content_type not in upload.allowed_mime:
        raise HTTPException(
            status_code=422, detail=f"content_type must be one of {list(upload.allowed_mime)}"
        )
    pack = platform.region_at(body.lat, body.lon)
    if pack is None:
        raise HTTPException(status_code=422, detail="Point is outside every onboarded region")
    if body.region_id is not None and body.region_id != pack.region_id:
        raise HTTPException(status_code=422, detail=f"Point is outside {body.region_id}")
    reporter = reporter_hash(platform.settings, claims.sub)
    limits = platform.citizen.rate_limits
    _limit(f"reporter:{reporter}", limits.per_reporter_per_hour)
    _limit(f"ip:{request.client.host if request.client else 'unknown'}", limits.per_ip_per_hour)

    report_id = f"cr_{secrets.token_hex(12)}"
    doc = CitizenReportDocument(
        report_id=report_id,
        region_id=pack.region_id,
        reporter_hash=reporter,
        claimed_lat=body.lat,
        claimed_lon=body.lon,
        device_accuracy_m=body.device_accuracy_m,
        client_captured_at=body.client_captured_at,
        observation_type=body.observation_type,
        notes=body.notes,
        created_at=platform.clock(),
        incoming_key=platform.storage.citizen.incoming_key(report_id),
    )
    platform.storage.citizen.create(doc)
    _record(platform, doc, "created")
    return {
        "report": _view(platform, doc, private=True),
        "upload": _upload_instruction(platform, doc, body.content_type),
    }


@router.post("/reports/{report_id}/media")
async def attach_media(
    report_id: str,
    claims: Annotated[TokenClaims, Depends(require(*REPORTER_ROLES))],
    platform: Annotated[ApiPlatform, Depends(get_platform)],
    analyzer: Annotated[AnalyzerClient | None, Depends(get_analyzer_client)],
    file: Annotated[UploadFile, File(...)],
) -> dict[str, Any]:
    """Local / dev multipart upload; on Google Cloud the signed URL is the path."""
    doc = _load(platform, report_id)
    own, _ = _access(platform, doc, claims)
    if not own and Role.ADMIN not in claims.roles:
        raise HTTPException(status_code=403, detail="Only the reporter may upload this photo")
    if doc.status != "awaiting_media" or doc.incoming_key is None:
        raise HTTPException(status_code=409, detail="This report already has a photo")
    upload = platform.citizen.upload
    payload = await file.read(upload.max_bytes + 1)
    if len(payload) > upload.max_bytes:
        raise HTTPException(status_code=413, detail=f"Photo exceeds {upload.max_bytes} bytes")
    mime = sniff(payload)
    if mime is None or mime not in upload.allowed_mime:
        raise HTTPException(status_code=400, detail="Upload must be a JPEG, PNG or WebP image")
    try:
        platform.storage.citizen.objects.put(
            doc.incoming_key, payload, content_type=mime, if_generation_match=0
        )
    except PreconditionFailedError as exc:
        raise HTTPException(status_code=409, detail="This report already has a photo") from exc

    def queued(d: CitizenReportDocument) -> CitizenReportDocument:
        d.status = "queued"
        return d

    doc = platform.storage.citizen.update(report_id, queued)
    _record(platform, doc, "uploaded")

    field_status: list[dict[str, str]] = []
    analysis = "not_triggered"
    if analyzer is None:
        field_status.append(
            {
                "field": "analysis",
                "reason": "AEROPULSE_CITIZEN_ANALYZER_URL is not set; run "
                f"`aeropulse-citizen analyze {report_id}`",
            }
        )
    else:
        try:
            analyzer.notify_upload(doc.incoming_key or "")
            analysis = "triggered"
        except AnalyzerUnavailableError as exc:
            log.warning("citizen.notify_failed", report_id=report_id, error=str(exc))
            field_status.append({"field": "analysis", "reason": str(exc)})
        doc = _load(platform, report_id)
    return {
        "report": _view(platform, doc, private=True),
        "analysis": analysis,
        "field_status": field_status,
    }


def _latest_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        current = latest.get(row["report_id"])
        if current is None or str(row["recorded_at"]) >= str(current["recorded_at"]):
            latest[row["report_id"]] = row
    return list(latest.values())


def _public_row(row: dict[str, Any]) -> dict[str, Any]:
    reasons = row.get("degraded_reasons")
    try:
        parsed = json.loads(reasons) if isinstance(reasons, str) else list(reasons or [])
    except ValueError:
        parsed = []
    out = {
        k: (v.isoformat() if hasattr(v, "isoformat") else v)
        for k, v in row.items()
        if k != "degraded_reasons"
    }
    out = {k: (None if isinstance(v, float) and v != v else v) for k, v in out.items()}
    out["degraded_reasons"] = parsed
    out["visual_class_provenance"] = (
        None
        if row.get("visual_class") is None
        else ("citizen" if row.get("visual_class_source") == "operator" else "ai_observation")
    )
    return out


@router.get("/reports")
def list_reports(
    claims: Annotated[TokenClaims, Depends(get_claims)],
    platform: Annotated[ApiPlatform, Depends(get_platform)],
    region_id: Annotated[str, Depends(region_id_param)],
    visual_class: Annotated[VisualClass | None, Query()] = None,
    corroboration: Annotated[
        str | None, Query(pattern="^(corroborated|partial|uncorroborated)$")
    ] = None,
    days: Annotated[int, Query(ge=1, le=365)] = LIST_DAYS,
    limit: Annotated[int | None, Query(ge=1, le=500)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    """Latest state of each report in the window, from ``citizen.reports``."""
    now = platform.clock()
    rows = platform.storage.analytics.query(
        "citizen.reports.window",
        {
            "region_id": region_id,
            "start": now - timedelta(days=days),
            "end": now + timedelta(minutes=1),
        },
        max_bytes=platform.storage.max_query_bytes,
    )
    items = [_public_row(r) for r in _latest_rows(rows)]
    if not _is_operator(claims):
        items = [
            r
            for r in items
            if r.get("moderation") != "rejected" and r.get("decision") != "stored_operators_only"
        ]
    if visual_class is not None:
        items = [r for r in items if r.get("visual_class") == visual_class]
    if corroboration is not None:
        items = [r for r in items if r.get("corroboration") == corroboration]
    items.sort(key=lambda r: (str(r.get("created_at")), r["report_id"]), reverse=True)
    return {**page(items, limit, offset), "region_id": region_id, "days": days}


@router.get("/reports/{report_id}")
def get_report(
    report_id: str,
    claims: Annotated[TokenClaims, Depends(get_claims)],
    platform: Annotated[ApiPlatform, Depends(get_platform)],
) -> dict[str, Any]:
    """Observation, geo-trust, corroboration signals and plume id."""
    doc = _load(platform, report_id)
    _, private = _access(platform, doc, claims)
    if not private and _operators_only(doc):
        raise HTTPException(status_code=404, detail=f"Report {report_id} not found")
    return _view(platform, doc, private=private)


@router.get("/reports/{report_id}/media")
def get_media(
    report_id: str,
    claims: Annotated[TokenClaims, Depends(get_claims)],
    platform: Annotated[ApiPlatform, Depends(get_platform)],
) -> dict[str, Any]:
    """A short-lived URL to the sanitized (EXIF-stripped) photo: operators or the reporter."""
    doc = _load(platform, report_id)
    _, private = _access(platform, doc, claims)
    if not private:
        raise HTTPException(
            status_code=403, detail="Photos are visible to operators and the reporter"
        )
    if doc.sanitized_key is None:
        raise HTTPException(status_code=404, detail="No sanitized photo for this report yet")
    ttl = platform.citizen.upload.signed_url_ttl_seconds
    if platform.storage.platform == "gcp":
        url = platform.storage.objects["citizen"].signed_download_url(doc.sanitized_key, ttl_s=ttl)
        return {"url": url, "expires_in_s": ttl}
    return {"url": f"/api/v1/citizen/reports/{report_id}/media/content", "expires_in_s": None}


@router.get("/reports/{report_id}/media/content")
def get_media_content(
    report_id: str,
    claims: Annotated[TokenClaims, Depends(get_claims)],
    platform: Annotated[ApiPlatform, Depends(get_platform)],
) -> Response:
    """Local stand-in for the signed download URL."""
    doc = _load(platform, report_id)
    _, private = _access(platform, doc, claims)
    if not private:
        raise HTTPException(
            status_code=403, detail="Photos are visible to operators and the reporter"
        )
    if doc.sanitized_key is None:
        raise HTTPException(status_code=404, detail="No sanitized photo for this report yet")
    try:
        stored = platform.storage.citizen.objects.get(doc.sanitized_key)
    except ObjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Sanitized photo missing") from exc
    return Response(
        content=stored.data,
        media_type=stored.content_type,
        headers={"Cache-Control": "private, no-store"},
    )


class ModerationBody(BaseModel):
    model_config = {"extra": "forbid"}

    action: str = Field(..., pattern="^(accept|reject|set_class)$")
    visual_class: VisualClass | None = None


@router.post("/reports/{report_id}/moderation")
def moderate(
    report_id: str,
    body: ModerationBody,
    _claims: Annotated[TokenClaims, Depends(require(*MODERATOR_ROLES))],
    platform: Annotated[ApiPlatform, Depends(get_platform)],
    analyzer: Annotated[AnalyzerClient | None, Depends(get_analyzer_client)],
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    """Accept, reject or re-class a report; the analyzer applies it and re-decides."""
    _load(platform, report_id)
    if analyzer is None:
        raise HTTPException(
            status_code=503,
            detail="Citizen analyzer not configured (AEROPULSE_CITIZEN_ANALYZER_URL)",
        )
    try:
        status, payload = analyzer.moderate(
            report_id, body.model_dump(mode="json"), authorization=authorization or ""
        )
    except AnalyzerUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if status != 200:
        raise HTTPException(status_code=status, detail=payload.get("detail", "moderation failed"))
    return payload
