"""Golden test (LLD APAC 5.2): the cycle produces the worker path's in-north events.

The baseline in ``in_north_events.json`` was recorded from the old worker
path (``process_*`` quality control, then ``process_snapshot`` with no
history) on the in-north replay fixtures, before the rule fixes below.

Intended differences, none of which changes an event on these fixtures:

* ``baseline-idw-0.2``: the PM2.5 estimate interpolates ground stations only.
  Model-derived (CAMS) points no longer enter it, and only observations from
  the same UTC hour count. Model-only cells now get no estimate (checked
  below); estimates do not decide whether an event is created.
* CAMS PM2.5 for the event forecast is the value for that cell and hour,
  never "the last value anywhere".
* The cycle passes each cell's PM2.5 history to the anomaly detector. A
  replay has no history, so the anomaly scores here match the baseline.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from aeropulse_common.settings import Settings
from aeropulse_cycle import CycleRunner
from aeropulse_cycle.detection import detect
from aeropulse_intelligence.snapshot import MODEL_DERIVED_SOURCES
from aeropulse_ml.preprocessing import PreprocessingPipeline
from aeropulse_ml.preprocessing.batch import PreprocessContext, RecordBatch
from aeropulse_regions import load_catalog
from aeropulse_regions.ingest import ingest_region
from aeropulse_storage import build_storage

GOLDEN = Path(__file__).with_name("in_north_events.json")


def _key(cells: list[str], severity: str, event_type: str, status: str) -> dict[str, object]:
    return {
        "cells": sorted(cells),
        "severity": severity,
        "event_type": event_type,
        "status": status,
    }


@pytest.fixture(scope="module")
def golden() -> dict[str, object]:
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def test_replay_cycle_matches_the_worker_baseline(
    golden: dict[str, object], tmp_path: Path
) -> None:
    clock = datetime.fromisoformat(str(golden["replay_clock"]))
    catalog = load_catalog(Path("config"))
    runner = CycleRunner(
        catalog,
        build_storage(Settings(data_dir=tmp_path)),
        fixtures_root=Path(str(golden["fixtures_root"])),
        clock=lambda: clock,
    )
    result = runner.run("in-north", clock, "replay")
    got = sorted(
        (
            _key(e.grid_ids, e.severity.value, e.event_type, e.status.value)
            for e in result.snapshot.events
        ),
        key=lambda k: k["cells"],  # type: ignore[arg-type, return-value]
    )
    expected = sorted(golden["events"], key=lambda k: k["cells"])  # type: ignore[arg-type, index]
    assert got == expected
    assert result.alerts_raised == [], "a replay never raises alerts"


def test_model_only_cells_get_no_station_estimate() -> None:
    catalog = load_catalog(Path("config"))
    pack = catalog.get("in-north")
    when = datetime(2026, 9, 8, 6, tzinfo=UTC)
    outcomes = ingest_region(pack, mode="replay", now=when, fixtures_root=Path("fixtures"))
    batch = RecordBatch.from_records(r for o in outcomes for r in o.records)
    cleaned, _ = PreprocessingPipeline().run(batch, PreprocessContext.for_region(pack, as_of=when))
    model_derived = MODEL_DERIVED_SOURCES | set(pack.model_derived_sources)
    result = detect(cleaned, cycle_time=when, previous=None, model_derived_sources=model_derived)
    stations = {
        o.grid_id
        for o in cleaned.observations
        if o.measurement.parameter == "pm25" and o.source_id not in model_derived
    }
    model_only = set(result.store.latest_features) - stations
    assert model_only, "the fixtures have CAMS-only cells"
    for cell in model_only:
        assert cell not in result.store.latest_predictions
