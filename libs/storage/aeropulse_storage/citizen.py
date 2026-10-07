"""Citizen reports without a database (LLD APAC 6.4).

The system of record is ``reports/{report_id}.json`` in the private citizen
bucket, written with generation preconditions so two writers cannot silently
overwrite each other (a conflict re-reads and retries). Originals land under
``incoming/{report_id}/{random}``, sanitized copies under
``sanitized/{report_id}.jpg``. ``hashes/{sha256}.json`` records the first
report with an image, which is the duplicate check.

Every state change also appends a row to ``citizen.reports``. Rows carry no
image, no raw reporter id and only rounded coordinates.
"""

from __future__ import annotations

import json
import re
import secrets
from collections.abc import Callable
from datetime import datetime
from typing import Any

from aeropulse_contracts.citizen import CitizenReportDocument
from pydantic import ValidationError

from aeropulse_storage.errors import ObjectNotFoundError, PreconditionFailedError, StorageError
from aeropulse_storage.objects import ObjectStore, check_key

REPORTS = "reports"
INCOMING = "incoming"
SANITIZED = "sanitized"
HASHES = "hashes"
#: Setting: optimistic-concurrency retries before giving up.
UPDATE_ATTEMPTS = 5

_REPORT_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def report_key(report_id: str) -> str:
    if not _REPORT_ID.match(report_id):
        raise StorageError(f"invalid report id: {report_id!r}")
    return check_key(f"{REPORTS}/{report_id}.json")


def report_id_from_incoming(key: str) -> str | None:
    """The report an ``incoming/{report_id}/...`` object belongs to, else ``None``."""
    parts = key.split("/")
    if len(parts) != 3 or parts[0] != INCOMING or not _REPORT_ID.match(parts[1]):
        return None
    return parts[1]


class CitizenReportStore:
    def __init__(self, objects: ObjectStore) -> None:
        self.objects = objects

    # --- documents ------------------------------------------------------

    def create(self, doc: CitizenReportDocument) -> int:
        """Write a new report; raises ``PreconditionFailedError`` if the id exists."""
        stored = self.objects.put(
            report_key(doc.report_id),
            doc.model_dump_json().encode(),
            content_type="application/json",
            if_generation_match=0,
        )
        return stored.generation

    def get(self, report_id: str) -> tuple[CitizenReportDocument, int] | None:
        key = report_key(report_id)
        try:
            stored = self.objects.get(key)
        except ObjectNotFoundError:
            return None
        try:
            return CitizenReportDocument.model_validate_json(stored.data), stored.generation
        except ValidationError as exc:
            raise StorageError(f"{key} does not match citizen_report.v2: {exc}") from exc

    def update(
        self,
        report_id: str,
        change: Callable[[CitizenReportDocument], CitizenReportDocument],
    ) -> CitizenReportDocument:
        """Read, apply ``change``, write if nobody wrote in between; retry otherwise."""
        last: PreconditionFailedError | None = None
        for _ in range(UPDATE_ATTEMPTS):
            current = self.get(report_id)
            if current is None:
                raise ObjectNotFoundError(f"report {report_id} does not exist")
            doc, generation = current
            updated = change(doc.model_copy(deep=True))
            try:
                self.objects.put(
                    report_key(report_id),
                    updated.model_dump_json().encode(),
                    content_type="application/json",
                    if_generation_match=generation,
                )
            except PreconditionFailedError as exc:
                last = exc
                continue
            return updated
        if last is None:
            raise ValueError("UPDATE_ATTEMPTS must be at least 1")
        raise last

    # --- media ----------------------------------------------------------

    def incoming_key(self, report_id: str) -> str:
        """A fresh random key, so two uploads never collide on a filename."""
        report_key(report_id)
        return check_key(f"{INCOMING}/{report_id}/{secrets.token_hex(16)}")

    def put_incoming(self, report_id: str, data: bytes, *, content_type: str) -> str:
        key = self.incoming_key(report_id)
        self.objects.put(key, data, content_type=content_type, if_generation_match=0)
        return key

    def read(self, key: str) -> bytes:
        return self.objects.get(check_key(key)).data

    def put_sanitized(self, report_id: str, data: bytes, *, content_type: str) -> str:
        report_key(report_id)
        key = check_key(f"{SANITIZED}/{report_id}.jpg")
        self.objects.put(key, data, content_type=content_type)
        return key

    def claim_hash(self, sha256: str, report_id: str) -> str:
        """The first report that submitted this image (``report_id`` if it is the first)."""
        if not _SHA256.match(sha256):
            raise StorageError("invalid sha256")
        key = check_key(f"{HASHES}/{sha256}.json")
        body = json.dumps({"report_id": report_id}).encode()
        try:
            self.objects.put(key, body, content_type="application/json", if_generation_match=0)
        except PreconditionFailedError:
            return str(json.loads(self.objects.get(key).data)["report_id"])
        return report_id


def citizen_row(
    doc: CitizenReportDocument, *, recorded_at: datetime, round_decimals: int
) -> dict[str, Any]:
    """One append-only ``citizen.reports`` row: public-safe fields only."""
    analysis = doc.analysis
    observation = analysis.observation if analysis else None
    corroboration = analysis.corroboration if analysis else None
    geo = analysis.geo_trust if analysis else None
    visual_class = doc.moderated_class or (observation.visual_class if observation else None)
    return {
        "report_id": doc.report_id,
        "region_id": doc.region_id,
        "recorded_at": recorded_at,
        "created_at": doc.created_at,
        "status": doc.status,
        "moderation": doc.moderation,
        "decision": analysis.decision if analysis else None,
        "visual_class": visual_class,
        "visual_class_source": "operator" if doc.moderated_class else "ai_observation",
        "geo_trust": geo.level if geo else None,
        "corroboration": corroboration.level if corroboration else None,
        "matched_fire_id": corroboration.matched_fire_id if corroboration else None,
        "plume_id": analysis.plume_id if analysis else None,
        "incident_id": analysis.incident_id if analysis else None,
        "observed_at": geo.observed_at if geo else None,
        "lat_rounded": round(doc.claimed_lat, round_decimals),
        "lon_rounded": round(doc.claimed_lon, round_decimals),
        "degraded_reasons": json.dumps(list(analysis.degraded_reasons) if analysis else []),
    }
