"""Plume stage (APAC LLD 8.2 and 8.4): which runs, with what inputs.

Forward runs: the top fire clusters by FRP, every open event, and every
seeded citizen report, each capped. Backward runs: every anomaly flag,
capped. The transport setup (profile, population, gazetteer) is
:class:`RegionTransport`, shared with the citizen analyzer.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import h3
from aeropulse_contracts import FieldStatus, FireCluster, PollutionEvent
from aeropulse_contracts.plume import Plume, PlumeOrigin, PlumeSummary
from aeropulse_contracts.snapshot import AnomalyFlag
from aeropulse_intelligence.plume import observed_wind, simulate
from aeropulse_intelligence.plume.region import (
    GAZETTEER_FILE,
    POPULATION_FILE,
    RegionTransport,
    transport_profile,
)
from aeropulse_ml.preprocessing.batch import RecordBatch
from aeropulse_regions import RegionCatalog
from aeropulse_storage import ObjectPlumeStore
from aeropulse_storage.snapshots import SnapshotMode

from aeropulse_cycle.detection import CLOSED

__all__ = [
    "BACKWARD_HOURS",
    "GAZETTEER_FILE",
    "MAX_BACKWARD_PLUMES",
    "MAX_EVENT_PLUMES",
    "MAX_FIRE_PLUMES",
    "POPULATION_FILE",
    "PlumeStageResult",
    "backward_origins",
    "forward_origins",
    "run_plumes",
    "transport_profile",
]

#: Settings: runs per cycle (LLD 8.2 "capped").
MAX_FIRE_PLUMES = 5
MAX_EVENT_PLUMES = 5
MAX_BACKWARD_PLUMES = 5
#: Settings: backward horizons, inside the LLD's 6-48 h range.
BACKWARD_HOURS: tuple[float, ...] = (6.0, 12.0, 24.0)


@dataclass
class PlumeStageResult:
    plumes: list[Plume] = field(default_factory=list)
    uris: list[str] = field(default_factory=list)
    field_status: list[FieldStatus] = field(default_factory=list)

    @property
    def summaries(self) -> list[PlumeSummary]:
        return [PlumeSummary.from_plume(p) for p in self.plumes]


def _cell_origin(kind: str, ref_id: str, grid_id: str) -> PlumeOrigin:
    lat, lon = h3.cell_to_latlng(grid_id)
    return PlumeOrigin(kind=kind, ref_id=ref_id, lat=lat, lon=lon)  # type: ignore[arg-type]


def forward_origins(
    fires: Sequence[FireCluster], events: Sequence[PollutionEvent]
) -> list[PlumeOrigin]:
    top = sorted(fires, key=lambda c: (-c.frp_total, c.cluster_id))[:MAX_FIRE_PLUMES]
    origins = [
        PlumeOrigin(kind="fire_cluster", ref_id=c.cluster_id, lat=c.lat, lon=c.lon) for c in top
    ]
    open_events = sorted(
        (e for e in events if e.status not in CLOSED and e.grid_ids),
        key=lambda e: (e.grid_ids[0], e.event_id),
    )
    origins += [
        _cell_origin("event", e.event_id, e.grid_ids[0]) for e in open_events[:MAX_EVENT_PLUMES]
    ]
    return origins


def backward_origins(anomalies: Sequence[AnomalyFlag]) -> list[PlumeOrigin]:
    top = sorted(anomalies, key=lambda a: (-a.score, a.grid_id))[:MAX_BACKWARD_PLUMES]
    return [_cell_origin("anomaly", a.grid_id, a.grid_id) for a in top]


def run_plumes(
    *,
    catalog: RegionCatalog,
    region_id: str,
    cycle_time: datetime,
    batch: RecordBatch,
    fires: Sequence[FireCluster],
    events: Sequence[PollutionEvent],
    anomalies: Sequence[AnomalyFlag],
    store: ObjectPlumeStore,
    mode: SnapshotMode,
    citizen: Sequence[PlumeOrigin] = (),
) -> PlumeStageResult:
    """Run, store, and summarise this cycle's plumes."""
    result = PlumeStageResult()
    transport = RegionTransport.load(catalog, region_id)
    if transport is None:
        result.field_status.append(
            FieldStatus(field="plumes", reason=f"no hazard in {region_id} runs a plume")
        )
        return result
    result.field_status += transport.field_status

    forward = forward_origins(fires, events) + list(citizen)
    backward = backward_origins(anomalies)
    if not forward and not backward:
        result.field_status.append(
            FieldStatus(
                field="plumes",
                reason="no fire cluster, open event, anomaly, or seeded citizen report",
            )
        )
        return result

    if forward:
        forward_inputs = transport.forward_inputs(batch.forecasts, batch.weather, cycle_time)
        if forward_inputs is None:
            result.field_status.append(
                FieldStatus(field="plumes", reason="no forecast or observed wind for forward runs")
            )
        else:
            result.plumes += [
                simulate(
                    region_id=region_id,
                    cycle_time=cycle_time,
                    direction="forward",
                    origin=o,
                    horizons_hours=transport.forward_hours,
                    inputs=forward_inputs,
                )
                for o in forward
            ]
    if backward:
        wind = observed_wind(
            batch.weather,
            start=cycle_time - timedelta(hours=max(BACKWARD_HOURS)),
            end=cycle_time,
            forecasts=batch.forecasts,
        )
        if wind.empty:
            result.field_status.append(
                FieldStatus(field="plumes", reason="no observed wind covers the backward window")
            )
        else:
            backward_inputs = transport.inputs(wind, fires=fires)
            result.plumes += [
                simulate(
                    region_id=region_id,
                    cycle_time=cycle_time,
                    direction="backward",
                    origin=o,
                    horizons_hours=BACKWARD_HOURS,
                    inputs=backward_inputs,
                )
                for o in backward
            ]
    result.uris = [store.write(p, mode=mode) for p in result.plumes]
    return result
