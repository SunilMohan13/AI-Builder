"""Geo-trust (LLD APAC 9.3): how far to trust where and when a photo was taken.

Deterministic. Each component is in [0, 1]; the score is their weighted mean
with the weights from ``config/citizen.yaml``. A claim outside the report's
region is untrusted whatever the other components say. ``observed_at`` is
the EXIF capture time when it is consistent with the upload, otherwise
``None`` with the reason; it is never set to server time.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import h3
from aeropulse_contracts.citizen import GeoTrust
from aeropulse_contracts.provenance import FieldStatus
from aeropulse_regions import RegionPack, bbox_contains_point
from aeropulse_regions.citizen import GeoTrustSettings

from aeropulse_vision.sanitize import ExifFacts


def geo_trust(
    *,
    pack: RegionPack,
    claimed_lat: float,
    claimed_lon: float,
    device_accuracy_m: float | None,
    received_at: datetime,
    exif: ExifFacts,
    duplicate: bool,
    settings: GeoTrustSettings,
) -> GeoTrust:
    in_region = bbox_contains_point(pack.geometry.bbox, claimed_lat, claimed_lon)
    components: dict[str, float] = {
        "in_region": 1.0 if in_region else 0.0,
        "exif_claim_distance": _distance(exif, claimed_lat, claimed_lon, settings),
        "device_accuracy": _accuracy(device_accuracy_m, settings),
        "not_duplicate": 0.0 if duplicate else 1.0,
    }
    captured = exif.capture_time(ZoneInfo(pack.timezone))
    components["time_consistency"], status = _timing(captured, received_at, settings)

    total = sum(settings.weights.values())
    score = sum(settings.weights[k] * components[k] for k in settings.weights) / total
    score = round(min(1.0, max(0.0, score)), 4)
    if not in_region or score < settings.usable_min:
        level = "untrusted"
    elif score >= settings.trusted_min:
        level = "trusted"
    else:
        level = "usable"
    consistent = status is None and captured is not None
    return GeoTrust(
        level=level,
        score=score,
        components={k: round(v, 4) for k, v in sorted(components.items())},
        region_id=pack.region_id if in_region else None,
        observed_at=captured if consistent else None,
        observed_at_status=status,
    )


def _distance(exif: ExifFacts, lat: float, lon: float, settings: GeoTrustSettings) -> float:
    if exif.lat is None or exif.lon is None:
        return settings.exif_absent_score
    km = h3.great_circle_distance((exif.lat, exif.lon), (lat, lon), unit="km")
    return max(0.0, 1.0 - km / settings.exif_claim_max_km)


def _accuracy(radius_m: float | None, settings: GeoTrustSettings) -> float:
    if radius_m is None:
        return 0.0
    good, bad = settings.device_accuracy_good_m, settings.device_accuracy_bad_m
    if radius_m <= good:
        return 1.0
    if radius_m >= bad:
        return 0.0
    return (bad - radius_m) / (bad - good)


def _timing(
    captured: datetime | None, received_at: datetime, settings: GeoTrustSettings
) -> tuple[float, FieldStatus | None]:
    if captured is None:
        return settings.exif_absent_score, FieldStatus(
            field="observed_at", reason="the photo has no EXIF capture time"
        )
    age_h = (received_at - captured).total_seconds() / 3600.0
    if age_h < 0:
        return 0.0, FieldStatus(field="observed_at", reason="EXIF capture time is after the upload")
    if age_h > settings.max_capture_age_hours:
        return 0.0, FieldStatus(
            field="observed_at",
            reason=f"EXIF capture time is more than {settings.max_capture_age_hours:g} h old",
        )
    return 1.0 - age_h / settings.max_capture_age_hours, None
