"""``scripts/build_gazetteer.py``: a pack's places from the GeoNames dump."""

from __future__ import annotations

import importlib.util
import shutil
import sys
import zipfile
from pathlib import Path
from types import ModuleType

import pytest
from aeropulse_intelligence.plume.region import GAZETTEER_FILE, load_places
from aeropulse_regions.registry import load_catalog

ROOT = Path(__file__).resolve().parents[2]


def _script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "build_gazetteer", ROOT / "scripts" / "build_gazetteer.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["build_gazetteer"] = module
    spec.loader.exec_module(module)
    return module


gz = _script()


def _row(
    gid: int, name: str, lat: float, lon: float, code: str, country: str, population: int
) -> str:
    cols = [""] * 19
    cols[0], cols[1], cols[4], cols[5] = str(gid), name, str(lat), str(lon)
    cols[6], cols[7], cols[8], cols[14] = "P", code, country, str(population)
    return "\t".join(cols)


# in-north: display bbox [73.5, 27.0, 78.5, 32.5], country IN, min_population 10000.
ROWS = [
    _row(1, "Big town", 30.9, 75.85, "PPL", "IN", 1_600_000),
    _row(2, "Capital", 28.65, 77.23, "PPLA", "IN", 11_000_000),
    _row(3, "Small town", 30.0, 76.0, "PPL", "IN", 9_999),
    _row(4, "Across the border", 31.55, 74.35, "PPLA", "PK", 11_000_000),
    _row(5, "Outside the box", 26.0, 80.0, "PPL", "IN", 500_000),
    _row(6, "Old fort", 29.0, 77.0, "PPLH", "IN", 50_000),
    _row(7, "Ward", 28.6, 77.2, "PPLX", "IN", 40_000),
]


def _zip(folder: Path, name: str = "cities5000") -> Path:
    path = folder / f"{name}.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(f"{name}.txt", "\n".join(ROWS) + "\n")
    return path


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    target = tmp_path / "config"
    shutil.copytree(ROOT / "config", target, ignore=shutil.ignore_patterns("models", "*.parquet"))
    return target


def test_dump_is_the_smallest_that_holds_the_floor() -> None:
    assert gz.dump_for(10_000) == "cities5000"
    assert gz.dump_for(15_000) == "cities15000"
    assert gz.dump_for(1_000) == "cities1000"
    with pytest.raises(ValueError):
        gz.dump_for(100)


def test_places_are_the_packs_own(tmp_path: Path) -> None:
    pack = load_catalog().get("in-north")
    places = gz.places_for(pack, gz.read_dump(_zip(tmp_path)))
    # Most populous first; PK, out-of-box, below-floor and historical places are dropped.
    assert list(places["place_id"]) == ["gn_2", "gn_1", "gn_7"]
    assert set(places["country_code"]) == {"IN"}
    assert list(places.columns) == gz.COLUMNS


def test_written_file_loads_as_plume_places(config_dir: Path, tmp_path: Path) -> None:
    dump = _zip(tmp_path)
    assert gz.main(["in-north", "--config-dir", str(config_dir), "--geonames-file", str(dump)]) == 0
    catalog = load_catalog(config_dir)
    assert (catalog.region_dir("in-north") / GAZETTEER_FILE).is_file()
    places = load_places(catalog.region_dir("in-north"), catalog.get("in-north"))
    assert places is not None
    assert [p.name for p in places] == ["Capital", "Big town", "Ward"]
    assert places[0].population == 11_000_000.0


def test_a_dump_above_the_floor_is_refused(config_dir: Path, tmp_path: Path) -> None:
    dump = _zip(tmp_path, "cities15000")
    args = ["in-north", "--config-dir", str(config_dir), "--geonames-file", str(dump)]
    assert gz.main(args) == 1
    assert not (config_dir / "regions" / "in-north" / GAZETTEER_FILE).exists()
