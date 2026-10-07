"""Region Pack validation (LLD APAC 4.2)."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml
from aeropulse_common.errors import RegionNotFoundError, RegionPackError
from aeropulse_regions import RegionPack, load_catalog, wind_sites
from aeropulse_regions.models import AqiStandard
from aeropulse_regions.validator import pack_issues
from pydantic import ValidationError

REPO = Path(__file__).resolve().parents[2]
CONFIG = REPO / "config"
FIXTURE_REGIONS = REPO / "tests" / "fixtures" / "regions"


def _pack_dict(region_id: str = "sg-singapore") -> dict[str, Any]:
    return yaml.safe_load((CONFIG / "regions" / region_id / "region.yaml").read_text())


def test_shipped_catalog_loads_three_regions() -> None:
    catalog = load_catalog(CONFIG)
    assert catalog.region_ids() == ["au-nsw", "in-north", "sg-singapore"]
    assert catalog.aqi_for("in-north").status == "confirmed"
    assert catalog.aqi_for("sg-singapore").status == "unconfirmed"
    assert catalog.aqi_for("au-nsw").status == "unconfirmed"


def test_synthetic_fourth_region_loads_with_no_code_change() -> None:
    catalog = load_catalog(CONFIG, extra_region_dirs=[FIXTURE_REGIONS])
    assert "zz-synthetic" in catalog.region_ids()
    pack = catalog.get("zz-synthetic")
    assert pack.ground_truth == "none"
    assert catalog.region_dir("zz-synthetic") == FIXTURE_REGIONS / "zz-synthetic"
    assert len(wind_sites(pack)) == pack.source_domain.max_wind_sites


def test_unknown_region_raises_typed_error() -> None:
    with pytest.raises(RegionNotFoundError):
        load_catalog(CONFIG).get("xx-nowhere")


def test_h3_resolution_must_be_eight() -> None:
    raw = _pack_dict()
    raw["h3_resolution"] = 7
    with pytest.raises(ValidationError):
        RegionPack.model_validate(raw)


def test_source_domain_must_contain_display_area() -> None:
    raw = _pack_dict()
    raw["source_domain"]["bbox"] = [103.7, 1.15, 104.1, 1.48]
    with pytest.raises(ValidationError, match=r"source_domain\.bbox must contain"):
        RegionPack.model_validate(raw)


def test_ground_truth_and_model_derived_cannot_overlap() -> None:
    raw = _pack_dict()
    raw["ground_truth_sources"] = ["openaq", "openmeteo"]
    with pytest.raises(ValidationError, match="both ground truth and model-derived"):
        RegionPack.model_validate(raw)


@pytest.mark.parametrize(
    "value",
    [
        "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",  # looks like a key value
        "sk_live_abcdef",
        "projects/p/secrets/",
        "openaq-api-key",
    ],
)
def test_secret_ref_rejects_values(value: str) -> None:
    raw = _pack_dict()
    raw["sources"][0]["secret_ref"] = value
    with pytest.raises(ValidationError, match="secret_ref"):
        RegionPack.model_validate(raw)


@pytest.mark.parametrize(
    "value",
    ["projects/<p>/secrets/openaq-api-key", "env:OPENAQ_KEY", "AEROPULSE_OPENAQ_API_KEY"],
)
def test_secret_ref_accepts_references(value: str) -> None:
    raw = _pack_dict()
    raw["sources"][0]["secret_ref"] = value
    RegionPack.model_validate(raw)


def test_unknown_timezone_rejected() -> None:
    raw = _pack_dict()
    raw["timezone"] = "Mars/Olympus"
    with pytest.raises(ValidationError, match="timezone"):
        RegionPack.model_validate(raw)


def test_extra_fields_forbidden() -> None:
    raw = _pack_dict()
    raw["surprise"] = True
    with pytest.raises(ValidationError):
        RegionPack.model_validate(raw)


def test_hazard_and_aqi_must_exist() -> None:
    catalog = load_catalog(CONFIG)
    raw = _pack_dict()
    raw["hazards"] = ["volcanic_ash"]
    raw["aqi_standard"] = "us_epa"
    pack = RegionPack.model_validate(raw)
    issues = pack_issues(
        pack, hazard_profiles=catalog.hazard_profiles, aqi_standards=catalog.aqi_standards
    )
    assert any("volcanic_ash" in i for i in issues)
    assert any("us_epa" in i for i in issues)


def test_unknown_source_rejected_when_registry_known() -> None:
    catalog = load_catalog(CONFIG)
    pack = catalog.get("sg-singapore")
    issues = pack_issues(
        pack,
        hazard_profiles=catalog.hazard_profiles,
        aqi_standards=catalog.aqi_standards,
        known_source_ids=["openaq", "firms"],
    )
    assert any("openmeteo" in i for i in issues)


def test_catalog_rejects_directory_name_mismatch(tmp_path: Path) -> None:
    config = tmp_path / "config"
    for sub in ("hazard_profiles", "aqi_standards"):
        (config / sub).mkdir(parents=True)
        for f in (CONFIG / sub).glob("*.yaml"):
            (config / sub / f.name).write_text(f.read_text())
    target = config / "regions" / "sg-wrong"
    target.mkdir(parents=True)
    (target / "region.yaml").write_text(yaml.safe_dump(_pack_dict()))
    with pytest.raises(RegionPackError, match="must match its directory"):
        load_catalog(config)


def test_cpcb_bands_moved_unchanged() -> None:
    from aeropulse_contracts.hazard import HAZARD_THRESHOLD_UGM3
    from aeropulse_copilot.tools import CPCB_PM25_BANDS

    cpcb = load_catalog(CONFIG).aqi_standards["cpcb_in"]
    as_tuples = [
        (b.low, b.high if b.high is not None else float("inf"), b.label) for b in cpcb.bands
    ]
    assert tuple(as_tuples) == CPCB_PM25_BANDS
    assert cpcb.hazard_threshold_ugm3 == HAZARD_THRESHOLD_UGM3


def test_unconfirmed_standard_classifies_nothing() -> None:
    nea = load_catalog(CONFIG).aqi_standards["sg_nea"]
    assert nea.classify(80.0) is None
    assert nea.reason


def test_unconfirmed_standard_cannot_carry_bands() -> None:
    raw = yaml.safe_load((CONFIG / "aqi_standards" / "sg_nea.yaml").read_text())
    raw["bands"] = [{"key": "a", "label": "A", "low": 0.0, "high": None}]
    with pytest.raises(ValidationError, match="unconfirmed"):
        AqiStandard.model_validate(raw)


def test_confirmed_bands_must_be_contiguous() -> None:
    raw = yaml.safe_load((CONFIG / "aqi_standards" / "cpcb_in.yaml").read_text())
    broken = copy.deepcopy(raw)
    broken["bands"][1]["low"] = 31.0
    with pytest.raises(ValidationError, match="contiguous"):
        AqiStandard.model_validate(broken)


def test_seasonal_months_come_from_hazard_profiles() -> None:
    catalog = load_catalog(CONFIG)
    assert catalog.seasonal_months("in-north") == {"is_stubble_season": frozenset({4, 5, 10, 11})}
    assert catalog.seasonal_months("sg-singapore") == {"is_haze_season": frozenset({8, 9, 10})}
    assert catalog.seasonal_months("au-nsw") == {}


def test_wind_sites_respect_budget_and_are_deterministic() -> None:
    catalog = load_catalog(CONFIG)
    for region_id in catalog.region_ids():
        pack = catalog.get(region_id)
        first = wind_sites(pack)
        assert len(first) <= pack.source_domain.max_wind_sites
        assert first == wind_sites(pack)
        assert any(s.in_display for s in first)
