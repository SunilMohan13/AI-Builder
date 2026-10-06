"""Citizen report APIs (LLD section 25.5). No trained computer vision in this pass."""

import re
from datetime import UTC, datetime
from pathlib import Path

from aeropulse_auth.jwt import Role, TokenClaims
from aeropulse_common.ids import new_ulid
from aeropulse_common.objects import put_raw_json
from aeropulse_contracts.citizen import CitizenReport
from aeropulse_geospatial.grid import to_grid_id
from aeropulse_intelligence.cv import classify_report
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from starlette.datastructures import UploadFile

from aeropulse_api.deps import get_claims, require
from aeropulse_api.event_store import current_store

router = APIRouter(prefix="/api/v1/citizen", tags=["citizen"])

MAX_PHOTO_BYTES = 5 * 1024 * 1024


class ReportCreate(BaseModel):
    """Citizen observation. cv_class is a notes keyword heuristic, not a CV model."""

    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    observation_type: str = "photo"
    notes: str | None = None


class MediaBody(BaseModel):
    """JSON attach used by Bruno; the same path also accepts a multipart file."""

    filename: str = "photo.jpg"
    content_type: str = "image/jpeg"


def _sniff_image(payload: bytes) -> str:
    """Return a content type, or 400 if the bytes are not a still image."""
    if len(payload) >= 3 and payload[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if payload.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(payload) >= 12 and payload[:4] == b"RIFF" and payload[8:12] == b"WEBP":
        return "image/webp"
    raise HTTPException(status_code=400, detail="Photo must be JPEG, PNG, or WebP")


def _safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", Path(name).name)[:80]
    return cleaned or "photo.jpg"


@router.post("/reports", status_code=201)
def create_report(
    body: ReportCreate,
    _claims: TokenClaims = Depends(require(Role.CITIZEN, Role.VIEWER, Role.ADMIN)),
) -> dict:
    """Store a citizen report. Does not create a HIGH pollution event."""
    report = CitizenReport(
        report_id=new_ulid("cit"),
        lat=body.lat,
        lon=body.lon,
        observed_at=datetime.now(UTC),
        observation_type=body.observation_type,
        notes=body.notes,
        cv_class="unknown",
        moderation="pending",
        grid_id=to_grid_id(body.lat, body.lon),
    )
    classify_report(report)
    store = current_store()
    for event in store.events.values():
        if report.grid_id and report.grid_id in event.grid_ids:
            report.correlated_event_id = event.event_id
            if event.severity.value not in {"HIGH", "CRITICAL"}:
                report.moderation = "accepted"
            break
    store.citizen_reports[report.report_id] = report
    return report.model_dump(mode="json")


@router.get("/reports")
def list_reports(
    _claims: TokenClaims = Depends(get_claims),
    limit: int | None = Query(default=None, ge=1, le=500, description="Max items to return"),
    offset: int = Query(default=0, ge=0, description="Items to skip"),
) -> dict:
    """List citizen reports currently held by the API event repository."""
    items = [report.model_dump(mode="json") for report in current_store().citizen_reports.values()]
    items.sort(key=lambda report: report["observed_at"], reverse=True)
    total = len(items)
    page = items[offset : offset + limit] if limit is not None else items[offset:]
    return {"items": page, "total": total, "limit": limit, "offset": offset}


@router.post("/reports/{report_id}/media", responses={404: {"description": "Report not found"}})
async def attach_media(
    report_id: str,
    request: Request,
    _claims: TokenClaims = Depends(require(Role.CITIZEN, Role.VIEWER, Role.ADMIN)),
) -> dict:
    """Attach a photo (multipart) or a JSON filename stub. Does not run a CV model."""
    report = current_store().citizen_reports.get(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")

    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        upload = form.get("file")
        if not isinstance(upload, UploadFile):
            raise HTTPException(status_code=400, detail="Missing photo file")
        payload = await upload.read()
        if len(payload) > MAX_PHOTO_BYTES:
            raise HTTPException(status_code=413, detail="Photo must be 5 MB or smaller")
        sniffed = _sniff_image(payload)
        filename = _safe_filename(getattr(upload, "filename", None) or "photo.jpg")
        uri = put_raw_json("citizen", filename, payload, content_type=sniffed)
    else:
        raw = await request.json()
        body = MediaBody.model_validate(raw)
        uri = put_raw_json(
            "citizen",
            _safe_filename(body.filename),
            b"placeholder",
            content_type=body.content_type,
        )

    report.media_uri = uri
    classify_report(report)
    return report.model_dump(mode="json")


@router.get("/reports/{report_id}", responses={404: {"description": "Report not found"}})
def get_report(report_id: str, _claims: TokenClaims = Depends(get_claims)) -> dict:
    """Fetch a citizen report."""
    report = current_store().citizen_reports.get(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return report.model_dump(mode="json")
