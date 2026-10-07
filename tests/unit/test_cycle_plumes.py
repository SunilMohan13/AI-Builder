"""The cycle's plume stage: which runs, where they are stored, what is missing."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import h3
import pandas as pd
import pytest
from aeropulse_common.settings import Settings
from aeropulse_contracts import (
    FireCluster,
    Location,
    MeteorologicalObservation,
    Provenance,
    Quality,
)
from aeropulse_cycle import CycleRunner
from aeropulse_cycle.plumes import (
    GAZETTEER_FILE,
    POPULATION_FILE,
    run_plumes,
    transport_profile,
)
from aeropulse_intelligence.plume import MODEL_VERSION
from aeropulse_ml.preprocessing.batch import RecordBatch
from aeropulse_regions import RegionCatalog, load_catalog
from aeropulse_storage import Storage, build_storage

T0 = datetime(2026, 9, 8, 6, tzinfo=UTC)
FIXTURES = Path("fixtures")


@pytest.fixture(scope="module")
def catalog() -> RegionCatalog:
    return load_catalog(Path("config"))


@pytest.fixture
def storage(tmp_path: Path) -> Storage:
    return build_storage(Settings(data_dir=tmp_path / "data"))


def test_each_region_has_a_transport_profile(catalog: RegionCatalog) -> None:
    keys = {r: getattr(transport_profile(catalog, r), "key", None) for r in catalog.region_ids()}
    assert keys == {
        "in-north": "crop_residue_burning",
        "sg-singapore": "transboundary_haze",
        "au-nsw": "bushfire_smoke",
    }


def test_replay_plumes_never_reach_the_live_plume_store(
    catalog: RegionCatalog, storage: Storage
) -> None:
    runner = CycleRunner(catalog, storage, fixtures_root=FIXTURES, clock=lambda: T0)
    snapshot = runner.run("in-north", T0, "replay").snapshot
    assert snapshot.plumes, "the in-north fixtures seed plumes"
    assert {p.direction for p in snapshot.plumes} == {"forward", "backward"}
    for summary in snapshot.plumes:
        assert storage.plumes.get("in-north", summary.plume_id) is None
        stored = storage.replay_plumes.get("in-north", summary.plume_id, mode="backfill")
        assert stored is not None and stored.model_version == MODEL_VERSION
        assert stored.provenance_class == "simulated" and stored.experimental

    fields = {f.field: f.reason for f in snapshot.field_status}
    assert "population raster not built" in fields["plumes.exposure"]
    assert "gazetteer not built" in fields["plumes.arrivals"]
    assert "plumes" not in fields


def test_forward_plumes_without_forecasts_persist_observed_wind_and_say_so(
    catalog: RegionCatalog, storage: Storage
) -> None:
    runner = CycleRunner(catalog, storage, fixtures_root=FIXTURES, clock=lambda: T0)
    snapshot = runner.run("in-north", T0, "replay").snapshot
    forward = [p for p in snapshot.plumes if p.direction == "forward"]
    assert forward
    for plume in forward:
        assert plume.degraded
        assert any(r.startswith("persisted_wind_after_") for r in plume.degraded_reasons)
        assert "wind_uncertainty_unmeasured" in plume.degraded_reasons
        assert plume.max_population_p90 is None
    kinds = {p.origin.kind for p in forward}
    assert kinds <= {"fire_cluster", "event"} and "fire_cluster" in kinds
    assert {p.origin.kind for p in snapshot.plumes if p.direction == "backward"} == {"anomaly"}


def test_plume_ids_are_stable_across_reruns(catalog: RegionCatalog, storage: Storage) -> None:
    runner = CycleRunner(catalog, storage, fixtures_root=FIXTURES, clock=lambda: T0)
    first = runner.run("in-north", T0, "replay").snapshot.plumes
    second = runner.run("in-north", T0, "replay").snapshot.plumes
    # Event ids are not stable across runs yet; the plume a re-run writes is.
    strip = {"origin": {"ref_id"}}
    assert [p.model_dump(exclude=strip) for p in first] == [
        p.model_dump(exclude=strip) for p in second
    ]


def _weather(at: datetime, lat: float, lon: float) -> MeteorologicalObservation:
    return MeteorologicalObservation(
        observation_id=f"wx_{at:%d%H}",
        source_id="openmeteo",
        source_record_id=f"wx_{at:%d%H}",
        observed_at=at,
        received_at=at,
        location=Location(lat=lat, lon=lon),
        quality=Quality(quality_flag="valid", quality_score=1.0),
        provenance=Provenance(provider="test", connector_version="0"),
        parameter="wind",
        wind_u=0.0,  # calm: particles stay in the origin cell, so exposure is exact
        wind_v=0.0,
    )


def test_onboarding_files_fill_exposure_and_arrivals(
    catalog: RegionCatalog, storage: Storage, tmp_path: Path
) -> None:
    lat, lon = 30.5, 75.8
    region_dir = tmp_path / "in-north"
    region_dir.mkdir()
    cell = h3.latlng_to_cell(lat, lon, 8)
    pd.DataFrame({"grid_id": [cell], "population": [2500.0], "year": [2020]}).to_parquet(
        region_dir / POPULATION_FILE
    )
    pd.DataFrame(
        {
            "place_id": ["gn_1", "gn_small"],
            "name": ["Fire town", "Hamlet"],
            "lat": [lat, lat],
            "lon": [lon, lon],
            "population": [40000.0, 50.0],
        }
    ).to_parquet(region_dir / GAZETTEER_FILE)
    onboarded = replace(catalog, region_dirs={**catalog.region_dirs, "in-north": region_dir})

    fire = FireCluster(
        cluster_id="c1",
        lat=lat,
        lon=lon,
        detection_count=2,
        frp_total=30.0,
        first_seen=T0 - timedelta(hours=3),
        last_seen=T0 - timedelta(hours=2),
        parent_cell=h3.latlng_to_cell(lat, lon, 6),
    )
    batch = RecordBatch().with_(
        weather=tuple(_weather(T0 - timedelta(hours=h), lat, lon) for h in range(3))
    )
    result = run_plumes(
        catalog=onboarded,
        region_id="in-north",
        cycle_time=T0,
        batch=batch,
        fires=[fire],
        events=[],
        anomalies=[],
        store=storage.plumes,
        mode="live",
    )
    assert {f.field for f in result.field_status} == set()
    (plume,) = result.plumes
    assert plume.exposure and plume.exposure[0].population_source == "worldpop"
    assert plume.exposure[0].population_year == 2020
    assert plume.exposure[0].population_p90 == pytest.approx(2500.0)
    assert [a.place_id for a in plume.arrivals] == ["gn_1"]  # below min_population: dropped
    assert plume.arrivals[0].probability == pytest.approx(1.0)
    assert result.uris[0].endswith(f"plumes/in-north/{plume.plume_id}.json")
    assert storage.plumes.get("in-north", plume.plume_id) == plume


def test_nothing_to_seed_says_so(catalog: RegionCatalog, storage: Storage) -> None:
    result = run_plumes(
        catalog=catalog,
        region_id="in-north",
        cycle_time=T0,
        batch=RecordBatch(),
        fires=[],
        events=[],
        anomalies=[],
        store=storage.plumes,
        mode="live",
    )
    assert result.plumes == []
    assert any(f.field == "plumes" and "no fire cluster" in f.reason for f in result.field_status)
