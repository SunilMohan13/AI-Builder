"""Citizen stage: which analysed reports this cycle carries (LLD APAC 9.6, 8.2).

A report the analyzer decided ``seed_plume`` (corroborated and trusted, or
accepted by an operator) within ``seed_window_hours`` seeds one forward plume
per cycle, capped, and appears in ``citizen_watches`` with its rounded point.
Nothing here touches events, predictions or labels.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from aeropulse_contracts import FieldStatus
from aeropulse_contracts.citizen import SMOKE_LIKE_CLASSES, CitizenReportDocument
from aeropulse_contracts.plume import Plume, PlumeOrigin
from aeropulse_contracts.snapshot import CitizenWatchSummary, FireCluster
from aeropulse_intelligence.corroboration import seeded_origin, watch_summary
from aeropulse_regions import CitizenSettings
from aeropulse_storage import Storage


def to_utc(value: object) -> datetime:
    moment = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


@dataclass
class CitizenStage:
    reports: list[CitizenReportDocument] = field(default_factory=list)
    field_status: list[FieldStatus] = field(default_factory=list)

    def origins(self, fires: Sequence[FireCluster], settings: CitizenSettings) -> list[PlumeOrigin]:
        spread = settings.decision.reporter_origin_spread_km
        found = (seeded_origin(d, fires, reporter_spread_km=spread) for d in self.reports)
        return [o for o in found if o is not None]

    def watches(
        self, plumes: Sequence[Plume], settings: CitizenSettings
    ) -> list[CitizenWatchSummary]:
        seeded = {
            p.origin.ref_id: p.plume_id
            for p in plumes
            if p.origin.kind == "citizen_report" and p.origin.ref_id
        }
        decimals = settings.decision.public_round_decimals
        found = (
            watch_summary(d, round_decimals=decimals, plume_id=seeded.get(d.report_id))
            for d in self.reports
        )
        return [w for w in found if w is not None]


def seeded_reports(
    storage: Storage, settings: CitizenSettings, region_id: str, cycle_time: datetime
) -> CitizenStage:
    stage = CitizenStage()
    window = settings.decision.seed_window_hours
    rows = storage.analytics.query(
        "citizen.reports.window",
        {
            "region_id": region_id,
            "start": cycle_time - timedelta(hours=window),
            "end": cycle_time + timedelta(hours=1),
        },
        max_bytes=storage.max_query_bytes,
    )
    latest: dict[str, dict[str, object]] = {}
    for row in rows:
        rid = str(row["report_id"])
        held = latest.get(rid)
        if held is None or to_utc(row["recorded_at"]) >= to_utc(held["recorded_at"]):
            latest[rid] = row
    acting = sorted(
        (
            r
            for r in latest.values()
            if r.get("decision") == "seed_plume"
            and r.get("moderation") != "rejected"
            and r.get("visual_class") in SMOKE_LIKE_CLASSES
        ),
        key=lambda r: (to_utc(r["recorded_at"]), str(r["report_id"])),
        reverse=True,
    )
    cap = settings.decision.max_plumes_per_cycle
    if len(acting) > cap:
        stage.field_status.append(
            FieldStatus(
                field="citizen_watches",
                reason=f"{len(acting) - cap} seeded report(s) over the per-cycle cap of {cap}",
            )
        )
    for row in acting[:cap]:
        found = storage.citizen.get(str(row["report_id"]))
        if found is not None:
            stage.reports.append(found[0])
    if not stage.reports:
        stage.field_status.append(
            FieldStatus(
                field="citizen_watches",
                reason=f"no corroborated citizen report in the last {window:g} h",
            )
        )
    return stage
