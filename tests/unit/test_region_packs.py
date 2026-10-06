"""Region packs reject invented standards and secret values."""

from pathlib import Path

import pytest
import yaml
from aeropulse_contracts.hazard import HAZARD_THRESHOLD_UGM3
from aeropulse_copilot.tools import CPCB_PM25_BANDS
from aeropulse_regions.loader import PackError, label_pm25, load_packs
from aeropulse_regions.models import AqiStandard, RegionPack

CONFIG = Path("config")


def test_three_packs_load() -> None:
    packs = load_packs(CONFIG)
    assert set(packs) == {"in-north", "sg-singapore", "au-nsw"}
    assert packs["in-north"].h3_resolution == 8
    assert packs["sg-singapore"].source_domain.as_bbox().contains(packs["sg-singapore"].geometry)


def test_unconfirmed_standards_do_not_label() -> None:
    packs = load_packs(CONFIG)
    standards = {
        path.stem: AqiStandard.model_validate(yaml.safe_load(path.read_text()))
        for path in (CONFIG / "aqi_standards").glob("*.yaml")
    }
    assert standards[packs["sg-singapore"].aqi_standard].confirmed is False
    assert label_pm25(standards["sg_nea"], 80.0) is None
    assert label_pm25(standards["cpcb_in"], 121.0) == "Very Poor"


def test_cpcb_yaml_matches_existing_constants() -> None:
    standard = AqiStandard.model_validate(
        yaml.safe_load((CONFIG / "aqi_standards" / "cpcb_in.yaml").read_text())
    )
    assert standard.hazard_threshold_ugm3 == HAZARD_THRESHOLD_UGM3
    rendered = [
        (band.low, band.high if band.high is not None else float("inf"), band.label)
        for band in standard.bands
    ]
    assert rendered == list(CPCB_PM25_BANDS)


def test_secret_value_is_rejected() -> None:
    raw = yaml.safe_load((CONFIG / "regions" / "in-north" / "region.yaml").read_text())
    raw["sources"][0]["secret_ref"] = "sk-live-secret-value-should-never-be-in-a-pack"
    with pytest.raises(ValueError):
        RegionPack.model_validate(raw)


def test_unknown_hazard_fails(tmp_path: Path) -> None:
    _copy_config(tmp_path)
    region = tmp_path / "regions" / "in-north" / "region.yaml"
    raw = yaml.safe_load(region.read_text())
    raw["hazards"] = ["not_a_profile"]
    region.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(PackError):
        load_packs(tmp_path)


def _copy_config(destination: Path) -> None:
    for path in CONFIG.rglob("*.yaml"):
        target = destination / path.relative_to(CONFIG)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
