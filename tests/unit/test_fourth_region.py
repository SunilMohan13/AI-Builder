"""A fourth region onboarded with configuration only, end to end.

The region is synthetic: the in-north replay fixtures moved 60 degrees south
into the open Indian Ocean, so the data is realistic but no pack in the repo
covers it. Onboarding uses ``aeropulse-region init`` plus a fixture path per
source and an unconfirmed AQI standard: YAML and JSON, no code. The real cycle
and the real API must then serve it, label it degraded where no model passed a
gate for it, never band it, and never mix it with another region.
"""

from __future__ import annotations

import json
import shutil
from datetime import timedelta
from pathlib import Path
from typing import Any

import h3
import pytest
import yaml
from aeropulse_api.platform import ApiPlatform
from aeropulse_common.settings import Settings
from aeropulse_contracts import RegionSnapshot
from aeropulse_cycle import CycleRunner
from aeropulse_regions import load_catalog, load_citizen_settings
from aeropulse_regions.cli import main as region_cli
from aeropulse_storage import build_storage
from region_cycle import T0, auth, client_for
from replayed_registry import replayed_registry

REGION = "zz-synthetic"
SHIFT_LAT = -60.0
IN_NORTH_BBOX = (73.5, 27.0, 78.5, 32.5)
BBOX = (
    IN_NORTH_BBOX[0],
    IN_NORTH_BBOX[1] + SHIFT_LAT,
    IN_NORTH_BBOX[2],
    IN_NORTH_BBOX[3] + SHIFT_LAT,
)
FIXTURES = {
    "openaq": "openaq/latest.json",
    "firms": "firms/fires.json",
    "openmeteo": "openmeteo/observations.json",
}
LAT_KEYS = {"lat", "latitude"}


def _shift(node: Any) -> Any:
    if isinstance(node, dict):
        return {
            k: v + SHIFT_LAT if k in LAT_KEYS and isinstance(v, int | float) else _shift(v)
            for k, v in node.items()
        }
    if isinstance(node, list):
        return [_shift(v) for v in node]
    return node


def _onboard(tmp: Path) -> tuple[Path, Path]:
    config = tmp / "config"
    shutil.copytree("config", config)
    (config / "aqi_standards" / "zz_test.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": "aqi_standard.v1",
                "key": "zz_test",
                "name": "Synthetic test standard",
                "pollutant": "pm25",
                "unit": "ug/m3",
                "status": "unconfirmed",
                "averaging": None,
                "source_url": None,
                "reason": "synthetic region: no official band table",
                "bands": [],
            }
        )
    )
    bbox = ",".join(str(v) for v in BBOX)
    assert (
        region_cli(
            [
                "--config-dir",
                str(config),
                "init",
                REGION,
                "--display-name",
                "Synthetic Ocean Test Region",
                "--country",
                "MU",
                "--timezone",
                "Indian/Mauritius",
                "--aqi-standard",
                "zz_test",
                "--bbox",
                bbox,
                "--hazards",
                "urban_pollution",
            ]
        )
        == 0
    )

    pack_path = config / "regions" / REGION / "region.yaml"
    pack = yaml.safe_load(pack_path.read_text())
    for source in pack["sources"]:
        source["fixture"] = FIXTURES[source["id"]]
    pack_path.write_text(yaml.safe_dump(pack, sort_keys=False))

    fixtures = tmp / "fixtures"
    for relative in FIXTURES.values():
        target = fixtures / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = json.loads((Path("fixtures") / relative).read_text())
        target.write_text(json.dumps(_shift(payload)))
    return config, fixtures


@pytest.fixture(scope="module")
def onboarded(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path, RegionSnapshot]:
    tmp = tmp_path_factory.mktemp("fourth-region")
    config, fixtures = _onboard(tmp)
    runner = CycleRunner(
        load_catalog(config),
        build_storage(Settings(data_dir=tmp / "data")),
        registry=replayed_registry(),
        fixtures_root=fixtures,
        clock=lambda: T0 + timedelta(minutes=5),
    )
    return tmp, config, runner.run(REGION, T0, "live").snapshot


def _inside(cell: str) -> bool:
    lat, lon = h3.cell_to_latlng(cell)
    return BBOX[0] <= lon <= BBOX[2] and BBOX[1] <= lat <= BBOX[3]


def test_the_pack_validates_beside_the_three_real_ones(
    onboarded: tuple[Path, Path, RegionSnapshot],
) -> None:
    _, config, _ = onboarded

    assert region_cli(["--config-dir", str(config), "validate"]) == 0
    assert load_catalog(config).region_ids() == [
        "au-nsw",
        "in-north",
        "sg-singapore",
        REGION,
    ]


def test_the_cycle_serves_the_region_from_its_own_data(
    onboarded: tuple[Path, Path, RegionSnapshot],
) -> None:
    _, _, snapshot = onboarded

    assert snapshot.region_id == REGION
    assert snapshot.cells, "the shifted stations and weather produced no cells"
    assert all(_inside(c.grid_id) for c in snapshot.cells)
    assert snapshot.events
    assert all(_inside(cell) for e in snapshot.events for cell in e.grid_ids)
    assert "in-north" not in snapshot.model_dump_json()


def test_every_model_is_a_degraded_baseline_and_no_band_is_invented(
    onboarded: tuple[Path, Path, RegionSnapshot],
) -> None:
    _, _, snapshot = onboarded

    gated = [m for m in snapshot.served_models if m.family != "source_likelihood"]
    assert gated
    for model in gated:
        assert model.degraded, model
        assert model.degraded_reason, model
    assert all(c.aqi_band is None for c in snapshot.cells)


def test_the_api_lists_it_and_answers_for_it_alone(
    onboarded: tuple[Path, Path, RegionSnapshot],
) -> None:
    tmp, config, _ = onboarded
    settings = Settings(data_dir=tmp / "data", config_dir=config)
    platform = ApiPlatform(
        settings=settings,
        catalog=load_catalog(config),
        storage=build_storage(settings),
        citizen=load_citizen_settings(config),
        clock=lambda: T0 + timedelta(minutes=10),
    )
    client = client_for(platform)
    headers = auth()

    regions = client.get("/api/v1/regions", headers=headers).json()
    assert REGION in [r["region_id"] for r in regions["items"]]

    detail = client.get(f"/api/v1/regions/{REGION}", headers=headers).json()
    assert detail["snapshot"]["cycle_time"].startswith("2026-09-08T06:00")
    assert detail["aqi_standard"]["status"] == "unconfirmed"

    grid = client.get(f"/api/v1/map/air-quality?region_id={REGION}", headers=headers).json()
    assert grid["data_source"]["kind"] != "not_configured"
    assert grid["features"]
    assert all(_inside(f["properties"]["grid_id"]) for f in grid["features"])

    other = client.get("/api/v1/map/air-quality?region_id=au-nsw", headers=headers).json()
    assert other["data_source"]["kind"] == "not_configured"
    assert other["features"] == []

    answer = client.post(
        "/api/v1/copilot/query",
        headers=headers,
        json={
            "question": "What is the air quality in Synthetic Ocean Test Region right now?",
            "region_id": REGION,
        },
    ).json()
    assert [c["name"] for c in answer["tool_calls"]] == ["get_current_aqi"]
    assert answer["grounding"]["grounded"]
    assert answer["grounding"]["numbers_checked"] > 0
    assert "in-north" not in json.dumps(answer)
