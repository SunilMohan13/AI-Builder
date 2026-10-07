"""Environmental corroboration of a citizen observation (LLD APAC 9.5, 9.6).

Deterministic. Each signal states its source, time and value; radii, windows
and weights come from ``config/citizen.yaml``. The score is the sum of the
weights of the supporting signals for the observed visual class, so a signal
that cannot be checked (no camera bearing, no aerosol reading, no station in
range) is neutral, never counted against the report. The result is
``heuristic``. Nothing here can create or change a pollution event.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

import h3
from aeropulse_contracts import EventStatus, PollutionEvent
from aeropulse_contracts.citizen import (
    SMOKE_LIKE_CLASSES,
    CitizenDecision,
    CitizenReportDocument,
    Corroboration,
    CorroborationSignal,
    GeoTrust,
)
from aeropulse_contracts.plume import Plume, PlumeOrigin
from aeropulse_contracts.provenance import ProvenanceClass
from aeropulse_contracts.snapshot import (
    AnomalyFlag,
    CellState,
    CitizenWatchSummary,
    FireCluster,
    WindVector,
)
from aeropulse_regions.citizen import CorroborationSettings

from aeropulse_intelligence.geometry import bearing_deg, haversine_km
from aeropulse_intelligence.plume.uncertainty import MIN_SPEED_FOR_DIRECTION

REPORT_RESOLUTION = 8
ACTIVE_EVENT_STATUSES = frozenset(
    {EventStatus.CONFIRMED, EventStatus.FORECASTING, EventStatus.ACTIVE, EventStatus.DECLINING}
)


@dataclass(frozen=True)
class AerosolReading:
    """S5P aerosol index anomaly at the report cell on the latest valid day."""

    elevated: bool
    source_id: str
    observed_at: datetime
    value: float | None = None


@dataclass(frozen=True)
class Environment:
    """What the latest cycle knows around the report."""

    fires: Sequence[FireCluster] = ()
    wind: Sequence[WindVector] = ()
    anomalies: Sequence[AnomalyFlag] = ()
    cells: Sequence[CellState] = ()
    plumes: Sequence[Plume] = ()
    events: Sequence[PollutionEvent] = ()
    #: Station PM2.5 history by grid id: ``(observed_at, pm25)``.
    station_series: Mapping[str, Sequence[tuple[datetime, float]]] | None = None
    aerosol: AerosolReading | None = None


@dataclass(frozen=True)
class ReportPoint:
    lat: float
    lon: float
    #: The time signals are compared against: EXIF capture time when trusted,
    #: else the upload time (stated in each time-based signal's detail).
    reference_time: datetime
    reference_is_capture: bool
    img_direction_deg: float | None = None


def corroborate(
    report: ReportPoint,
    visual_class: str,
    env: Environment,
    settings: CorroborationSettings,
) -> Corroboration:
    weights = settings.weights_for(visual_class)
    basis = (
        "capture time" if report.reference_is_capture else "upload time (no trusted capture time)"
    )
    fires = _recent_fires(env.fires, report.reference_time, settings.fire_window_hours)

    nearby = _nearest(report, fires, settings.fire_radius_km)
    on_bearing = _on_bearing(report, fires, settings)
    matched = on_bearing[0] if on_bearing else (nearby[0] if nearby else None)

    signals = [
        _fire_signal(
            "fire_nearby",
            nearby,
            weights,
            f"within {settings.fire_radius_km:g} km, ±{settings.fire_window_hours:g} h of {basis}",
        ),
        _bearing_signal(report, on_bearing, weights, settings),
        _upwind_signal(report, matched, env.wind, weights, settings),
        _plume_signal(report, env.plumes, weights),
        _pm25_signal(report, env, weights, settings),
        _aerosol_signal(env.aerosol, weights),
        _event_signal(report, env.events, weights),
    ]
    score = round(sum(s.weight for s in signals if s.supports), 4)
    if not weights:
        level = "uncorroborated"
    elif score >= settings.corroborated_min:
        level = "corroborated"
    elif score >= settings.partial_min:
        level = "partial"
    else:
        level = "uncorroborated"
    return Corroboration(
        level=level,
        score=score,
        method_version=settings.method_version,
        signals=signals,
        matched_fire_id=matched.cluster_id if matched else None,
    )


def decide(
    *,
    visual_class: str | None,
    geo: GeoTrust,
    corroboration: Corroboration | None,
) -> CitizenDecision:
    """The LLD 9.6 decision table. Only ``seed_plume`` lets a report act."""
    if geo.level == "untrusted" or visual_class is None:
        return "operator_queue"
    if visual_class not in SMOKE_LIKE_CLASSES:
        return "no_smoke_observed"
    if corroboration is None:
        return "operator_queue"
    if corroboration.level == "uncorroborated":
        return "stored_operators_only"
    if corroboration.level == "corroborated" and geo.level == "trusted":
        return "seed_plume"
    return "operator_queue"


def plume_origin(
    report_id: str,
    report: ReportPoint,
    corroboration: Corroboration,
    fires: Sequence[FireCluster],
    *,
    reporter_spread_km: float,
) -> PlumeOrigin:
    """The fire on the camera bearing if one matched, else the reporter with a wider start."""
    bearing = next((s for s in corroboration.signals if s.signal == "fire_on_bearing"), None)
    if bearing is not None and bearing.supports and corroboration.matched_fire_id:
        fire = next((f for f in fires if f.cluster_id == corroboration.matched_fire_id), None)
        if fire is not None:
            return PlumeOrigin(kind="citizen_report", ref_id=report_id, lat=fire.lat, lon=fire.lon)
    return PlumeOrigin(
        kind="citizen_report",
        ref_id=report_id,
        lat=report.lat,
        lon=report.lon,
        initial_spread_km=reporter_spread_km,
    )


def seeded_origin(
    doc: CitizenReportDocument, fires: Sequence[FireCluster], *, reporter_spread_km: float
) -> PlumeOrigin | None:
    """The plume origin of a report that seeds one, from its stored analysis."""
    analysis = doc.analysis
    if analysis is None or analysis.decision != "seed_plume" or analysis.corroboration is None:
        return None
    geo = analysis.geo_trust
    point = ReportPoint(
        lat=doc.claimed_lat,
        lon=doc.claimed_lon,
        reference_time=(geo.observed_at if geo else None) or doc.created_at,
        reference_is_capture=geo is not None and geo.observed_at is not None,
    )
    return plume_origin(
        doc.report_id,
        point,
        analysis.corroboration,
        fires,
        reporter_spread_km=reporter_spread_km,
    )


def watch_summary(
    doc: CitizenReportDocument, *, round_decimals: int, plume_id: str | None
) -> CitizenWatchSummary | None:
    """The public view of a corroborated report: rounded point, class, corroboration."""
    analysis = doc.analysis
    if analysis is None or analysis.corroboration is None:
        return None
    observation = analysis.observation
    visual_class = doc.moderated_class or (observation.visual_class if observation else None)
    if visual_class is None:
        return None
    return CitizenWatchSummary(
        report_id=doc.report_id,
        lat_rounded=round(doc.claimed_lat, round_decimals),
        lon_rounded=round(doc.claimed_lon, round_decimals),
        visual_class=visual_class,
        corroboration=analysis.corroboration.level,
        plume_id=plume_id,
        matched_fire_id=analysis.corroboration.matched_fire_id,
        observed_at=analysis.geo_trust.observed_at if analysis.geo_trust else None,
        provenance_class="citizen" if doc.moderated_class else "ai_observation",
    )


# --- signals ---------------------------------------------------------------


def _recent_fires(
    fires: Sequence[FireCluster], at: datetime, window_hours: float
) -> list[FireCluster]:
    window = timedelta(hours=window_hours)
    return [f for f in fires if f.first_seen - window <= at <= f.last_seen + window]


def _nearest(
    report: ReportPoint, fires: Sequence[FireCluster], radius_km: float
) -> tuple[FireCluster, float] | None:
    ranked = sorted(
        ((f, haversine_km(report.lat, report.lon, f.lat, f.lon)) for f in fires),
        key=lambda pair: (pair[1], pair[0].cluster_id),
    )
    return next(((f, d) for f, d in ranked if d <= radius_km), None)


def _on_bearing(
    report: ReportPoint, fires: Sequence[FireCluster], settings: CorroborationSettings
) -> tuple[FireCluster, float] | None:
    if report.img_direction_deg is None:
        return None
    hits = []
    for fire in fires:
        km = haversine_km(report.lat, report.lon, fire.lat, fire.lon)
        off = _angle(
            bearing_deg(report.lat, report.lon, fire.lat, fire.lon), report.img_direction_deg
        )
        if km <= settings.bearing_max_km and off <= settings.bearing_cone_deg:
            hits.append((fire, km))
    hits.sort(key=lambda pair: (pair[1], pair[0].cluster_id))
    return hits[0] if hits else None


def _fire_signal(
    name: str,
    match: tuple[FireCluster, float] | None,
    weights: Mapping[str, float],
    detail: str,
) -> CorroborationSignal:
    if match is None:
        return CorroborationSignal(
            signal=name,
            supports=False,
            weight=weights.get(name, 0.0),
            detail=f"no FIRMS cluster {detail}",
        )
    fire, km = match
    return CorroborationSignal(
        signal=name,
        supports=True,
        weight=weights.get(name, 0.0),
        source_id=",".join(fire.source_ids) or "firms",
        observed_at=fire.last_seen,
        value=round(km, 2),
        detail=f"cluster {fire.cluster_id}, {detail}",
    )


def _bearing_signal(
    report: ReportPoint,
    match: tuple[FireCluster, float] | None,
    weights: Mapping[str, float],
    settings: CorroborationSettings,
) -> CorroborationSignal:
    if report.img_direction_deg is None:
        return CorroborationSignal(
            signal="fire_on_bearing",
            supports=None,
            weight=weights.get("fire_on_bearing", 0.0),
            detail="the photo has no camera bearing (EXIF GPSImgDirection)",
        )
    return _fire_signal(
        "fire_on_bearing",
        match,
        weights,
        f"within ±{settings.bearing_cone_deg:g}° of the camera bearing "
        f"{report.img_direction_deg:.0f}°, up to {settings.bearing_max_km:g} km",
    )


def _upwind_signal(
    report: ReportPoint,
    fire: FireCluster | None,
    wind: Sequence[WindVector],
    weights: Mapping[str, float],
    settings: CorroborationSettings,
) -> CorroborationSignal:
    weight = weights.get("fire_upwind", 0.0)
    vector = _wind_at(report, wind)
    if vector is None:
        return CorroborationSignal(
            signal="fire_upwind", supports=None, weight=weight, detail="no wind near the report"
        )
    speed = math.hypot(vector.u, vector.v)
    if speed < MIN_SPEED_FOR_DIRECTION:
        return CorroborationSignal(
            signal="fire_upwind",
            supports=None,
            weight=weight,
            source_id=vector.site_id,
            observed_at=vector.valid_at,
            value=round(speed, 2),
            detail="wind too light to have a direction",
        )
    blowing_from = (math.degrees(math.atan2(-vector.u, -vector.v)) + 360.0) % 360.0
    if fire is None:
        return CorroborationSignal(
            signal="fire_upwind",
            supports=False,
            weight=weight,
            source_id=vector.site_id,
            observed_at=vector.valid_at,
            value=round(blowing_from, 1),
            detail="no matched fire to test",
        )
    off = _angle(bearing_deg(report.lat, report.lon, fire.lat, fire.lon), blowing_from)
    return CorroborationSignal(
        signal="fire_upwind",
        supports=off <= settings.upwind_cone_deg,
        weight=weight,
        source_id=vector.site_id,
        observed_at=vector.valid_at,
        value=round(blowing_from, 1),
        detail=(
            f"wind from {blowing_from:.0f}° ({vector.provenance_class}); fire {fire.cluster_id} "
            f"is {off:.0f}° off it (cone ±{settings.upwind_cone_deg:g}°)"
        ),
    )


def _plume_signal(
    report: ReportPoint, plumes: Sequence[Plume], weights: Mapping[str, float]
) -> CorroborationSignal:
    weight = weights.get("on_plume_path", 0.0)
    cell = h3.latlng_to_cell(report.lat, report.lon, REPORT_RESOLUTION)
    ancestors = {cell, *(h3.cell_to_parent(cell, r) for r in range(REPORT_RESOLUTION))}
    for plume in sorted(plumes, key=lambda p: p.plume_id):
        if plume.direction != "forward":
            continue
        for horizon in plume.horizons:
            if ancestors & set(horizon.p90_cells):
                return CorroborationSignal(
                    signal="on_plume_path",
                    supports=True,
                    weight=weight,
                    source_id=plume.model_version,
                    observed_at=plume.release_time,
                    value=plume.plume_id,
                    detail=f"inside the P90 footprint at {horizon.horizon_hours:g} h (simulated)",
                )
    return CorroborationSignal(
        signal="on_plume_path",
        supports=False,
        weight=weight,
        detail="outside every forward plume's P90 footprint",
    )


def _pm25_signal(
    report: ReportPoint,
    env: Environment,
    weights: Mapping[str, float],
    settings: CorroborationSettings,
) -> CorroborationSignal:
    weight = weights.get("pm25_elevated", 0.0)
    stations = sorted(
        (
            (haversine_km(report.lat, report.lon, c.lat, c.lon), c)
            for c in env.cells
            if c.provenance_class == ProvenanceClass.MEASURED and c.pm25_source_id
        ),
        key=lambda pair: (pair[0], pair[1].grid_id),
    )
    in_range = [(km, c) for km, c in stations if km <= settings.station_radius_km]
    if not in_range:
        return CorroborationSignal(
            signal="pm25_elevated",
            supports=None,
            weight=weight,
            detail=f"no ground station within {settings.station_radius_km:g} km",
        )
    km, station = in_range[0]
    flag = next((a for a in env.anomalies if a.grid_id == station.grid_id), None)
    if flag is not None:
        return CorroborationSignal(
            signal="pm25_elevated",
            supports=True,
            weight=weight,
            source_id=station.pm25_source_id,
            observed_at=flag.observed_at,
            value=flag.observed_pm25,
            detail=f"station {km:.1f} km away is above its expected range ({flag.method_version})",
        )
    series = (env.station_series or {}).get(station.grid_id, ())
    start = report.reference_time - timedelta(hours=settings.pm25_rise_window_hours)
    window = sorted((t, v) for t, v in series if start <= t <= report.reference_time)
    rising = len(window) >= 2 and window[-1][1] > window[0][1]
    return CorroborationSignal(
        signal="pm25_elevated",
        supports=rising,
        weight=weight,
        source_id=station.pm25_source_id,
        observed_at=window[-1][0] if window else station.observed_at,
        value=window[-1][1] if window else station.pm25,
        detail=(
            f"station {km:.1f} km away rose over {settings.pm25_rise_window_hours:g} h"
            if rising
            else f"station {km:.1f} km away is within its expected range and not rising"
        ),
    )


def _aerosol_signal(
    reading: AerosolReading | None, weights: Mapping[str, float]
) -> CorroborationSignal:
    weight = weights.get("aerosol_index_elevated", 0.0)
    if reading is None:
        return CorroborationSignal(
            signal="aerosol_index_elevated",
            supports=None,
            weight=weight,
            detail="no valid aerosol index for this cell (often cloud); neutral",
        )
    return CorroborationSignal(
        signal="aerosol_index_elevated",
        supports=reading.elevated,
        weight=weight,
        source_id=reading.source_id,
        observed_at=reading.observed_at,
        value=reading.value,
    )


def _event_signal(
    report: ReportPoint, events: Sequence[PollutionEvent], weights: Mapping[str, float]
) -> CorroborationSignal:
    weight = weights.get("active_event", 0.0)
    cell = h3.latlng_to_cell(report.lat, report.lon, REPORT_RESOLUTION)
    ring = set(h3.grid_disk(cell, 1))
    for event in sorted(events, key=lambda e: e.event_id):
        if event.status in ACTIVE_EVENT_STATUSES and ring & set(event.grid_ids):
            return CorroborationSignal(
                signal="active_event",
                supports=True,
                weight=weight,
                source_id=",".join(event.model_versions) or "event-engine",
                observed_at=event.updated_at,
                value=event.event_id,
                detail=f"{event.status.value} event covers the cell or a neighbour",
            )
    return CorroborationSignal(
        signal="active_event", supports=False, weight=weight, detail="no active event here"
    )


def _wind_at(report: ReportPoint, wind: Sequence[WindVector]) -> WindVector | None:
    near = [w for w in wind if w.level == "10m"]
    if not near:
        return None
    site = min(
        near, key=lambda w: (haversine_km(report.lat, report.lon, w.lat, w.lon), w.site_id)
    ).site_id
    at_site = [w for w in near if w.site_id == site]
    return min(
        at_site,
        key=lambda w: (
            abs((w.valid_at - report.reference_time).total_seconds()),
            w.issued_at is not None,
        ),
    )


def _angle(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)
