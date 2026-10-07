"""Map layers the snapshot carries: cell PM2.5, fire clusters, wind (LLD APAC 6.3).

Every function reads a batch already preprocessed at the cycle time, so a
value is never shown before it was knowable.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Literal

import h3
from aeropulse_contracts import (
    AqiBandRef,
    CellState,
    FieldStatus,
    FireCluster,
    Observation,
    ProvenanceClass,
    WindVector,
)
from aeropulse_ml.features.tables import site_key
from aeropulse_ml.preprocessing.batch import PreprocessContext, RecordBatch
from aeropulse_ml.preprocessing.steps import hour_ending
from aeropulse_regions import AqiStandard, RegionPack

#: Settings: a cell shows PM2.5 only if its newest value is this recent.
DISPLAY_MAX_AGE_HOURS = 3
#: Settings: FIRMS detections grouped per H3 parent at this resolution (LLD 8.2).
FIRE_CLUSTER_RESOLUTION = 6
#: Settings: detections older than this leave the fire layer.
FIRE_WINDOW_HOURS = 24
#: Settings: forecast wind is shown for the next this-many hours.
WIND_FORECAST_HOURS = 6


def _provenance(obs: Observation, context: PreprocessContext) -> ProvenanceClass:
    if obs.provenance.provenance_class is not None:
        return obs.provenance.provenance_class
    if context.is_model_derived(obs):
        return ProvenanceClass.MODEL_DERIVED
    return ProvenanceClass.MEASURED


def cell_states(
    batch: RecordBatch,
    context: PreprocessContext,
    aqi: AqiStandard,
    cycle_time: datetime,
) -> list[CellState]:
    """One state per cell with PM2.5 in the batch; stale or missing values say why.

    ``batch`` must come from the display pipeline, so a station already
    outranks a model value in the same cell-hour.
    """
    by_cell: dict[str, dict[datetime, Observation]] = defaultdict(dict)
    for obs in batch.observations:
        if obs.measurement.parameter != "pm25" or obs.grid_id is None:
            continue
        tau = hour_ending(obs.observed_at)
        held = by_cell[obs.grid_id].get(tau)
        rank = (context.is_ground_truth(obs), obs.observed_at)
        if held is None or rank > (context.is_ground_truth(held), held.observed_at):
            by_cell[obs.grid_id][tau] = obs

    oldest = cycle_time - timedelta(hours=DISPLAY_MAX_AGE_HOURS)
    states: list[CellState] = []
    for grid_id in sorted(by_cell):
        lat, lon = h3.cell_to_latlng(grid_id)
        hours = by_cell[grid_id]
        recent = [tau for tau in hours if oldest < tau <= cycle_time]
        if not recent:
            states.append(
                CellState(
                    grid_id=grid_id,
                    lat=lat,
                    lon=lon,
                    pm25=None,
                    field_status=[
                        FieldStatus(
                            field="pm25",
                            reason=f"no PM2.5 in the last {DISPLAY_MAX_AGE_HOURS} h",
                        )
                    ],
                )
            )
            continue
        tau = max(recent)
        current = hours[tau]
        provenance = _provenance(current, context)
        band, status = _band(aqi, hours, tau, provenance, context)
        states.append(
            CellState(
                grid_id=grid_id,
                lat=lat,
                lon=lon,
                pm25=current.measurement.value,
                pm25_source_id=current.source_id,
                provenance_class=provenance,
                observed_at=current.observed_at,
                aqi_band=band,
                field_status=status,
            )
        )
    return states


def _band(
    aqi: AqiStandard,
    hours: dict[datetime, Observation],
    tau: datetime,
    provenance: ProvenanceClass,
    context: PreprocessContext,
) -> tuple[AqiBandRef | None, list[FieldStatus]]:
    """Band in the region's standard, over the standard's own averaging period."""
    if not aqi.bands:
        reason = aqi.reason or f"{aqi.name} has no confirmed bands"
        return None, [FieldStatus(field="aqi_band", reason=reason)]
    if aqi.averaging == "24h":
        window = [
            obs.measurement.value
            for t, obs in hours.items()
            if tau - timedelta(hours=24) < t <= tau and _provenance(obs, context) == provenance
        ]
        needed = aqi.averaging_min_hours or 24
        if len(window) < needed:
            reason = (
                f"{aqi.name} uses a 24 h mean of at least {needed} hourly values; "
                f"{len(window)} available"
            )
            return None, [FieldStatus(field="aqi_band", reason=reason)]
        value = sum(window) / len(window)
    else:
        value = hours[tau].measurement.value
    band = aqi.classify(value)
    if band is None:
        return None, [FieldStatus(field="aqi_band", reason="value outside the standard's bands")]
    ref = AqiBandRef(standard=aqi.key, key=band.key, label=band.label, colour=band.colour)
    return ref, []


def fire_clusters(batch: RecordBatch, cycle_time: datetime) -> list[FireCluster]:
    """FIRMS detections in the last day, grouped by coarse H3 parent."""
    oldest = cycle_time - timedelta(hours=FIRE_WINDOW_HOURS)
    groups: dict[str, list] = defaultdict(list)
    for fire in batch.fires:
        if oldest < fire.observed_at <= cycle_time:
            parent = h3.latlng_to_cell(
                fire.location.lat, fire.location.lon, FIRE_CLUSTER_RESOLUTION
            )
            groups[parent].append(fire)
    clusters: list[FireCluster] = []
    for parent in sorted(groups):
        members = groups[parent]
        first = min(f.observed_at for f in members)
        clusters.append(
            FireCluster(
                cluster_id=f"{parent}:{first:%Y%m%dT%H%MZ}",
                lat=sum(f.location.lat for f in members) / len(members),
                lon=sum(f.location.lon for f in members) / len(members),
                detection_count=len(members),
                frp_total=round(sum(f.fire.frp for f in members), 3),
                first_seen=first,
                last_seen=max(f.observed_at for f in members),
                parent_cell=parent,
                source_ids=sorted({f.source_id for f in members}),
            )
        )
    return clusters


def wind_vectors(batch: RecordBatch, pack: RegionPack, cycle_time: datetime) -> list[WindVector]:
    """Newest observed wind per site, then forecast wind for the next hours."""
    oldest = cycle_time - timedelta(hours=DISPLAY_MAX_AGE_HOURS)
    observed: dict[str, WindVector] = {}
    for wx in batch.weather:
        if wx.wind_u is None or wx.wind_v is None or not (oldest < wx.observed_at <= cycle_time):
            continue
        site = site_key(wx.location.lat, wx.location.lon)
        held = observed.get(site)
        if held is not None and held.valid_at >= wx.observed_at:
            continue
        observed[site] = WindVector(
            site_id=site,
            lat=wx.location.lat,
            lon=wx.location.lon,
            valid_at=wx.observed_at,
            u=wx.wind_u,
            v=wx.wind_v,
            provenance_class=wx.provenance.provenance_class or ProvenanceClass.MODEL_DERIVED,
        )
    sites = sorted(observed)[: pack.source_domain.max_wind_sites]
    vectors = [observed[s] for s in sites]

    horizon = cycle_time + timedelta(hours=WIND_FORECAST_HOURS)
    forecast: list[WindVector] = []
    for fc in batch.forecasts:
        if not (cycle_time < fc.valid_at <= horizon) or fc.issued_at > cycle_time:
            continue
        levels: tuple[tuple[Literal["10m", "100m"], float | None, float | None], ...] = (
            ("10m", fc.wind_u_10m, fc.wind_v_10m),
            ("100m", fc.wind_u_100m, fc.wind_v_100m),
        )
        for level, u, v in levels:
            if u is None or v is None:
                continue
            forecast.append(
                WindVector(
                    site_id=fc.site_id,
                    lat=fc.location.lat,
                    lon=fc.location.lon,
                    valid_at=fc.valid_at,
                    issued_at=fc.issued_at,
                    u=u,
                    v=v,
                    level=level,
                    provenance_class=fc.provenance.provenance_class
                    or ProvenanceClass.MODEL_DERIVED,
                )
            )
    keep = set(sorted({w.site_id for w in forecast})[: pack.source_domain.max_wind_sites])
    forecast = [w for w in forecast if w.site_id in keep]
    forecast.sort(key=lambda w: (w.site_id, w.valid_at, w.level))
    return vectors + forecast
