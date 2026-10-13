"""Build a region's ``gazetteer.parquet`` from the GeoNames cities dump.

The plume engine reports a forward plume's arrivals against this file; without
it every plume reaches no place and no fire-to-town incident can form. Places
are the pack's own: inside ``geometry.bbox``, in one of ``country_codes``, at
or above ``gazetteer.min_population``. Historical, abandoned and destroyed
places are dropped.

    uv run python scripts/build_gazetteer.py in-north sg-singapore

Requires network access to download.geonames.org unless ``--geonames-file``
points at a downloaded ``citiesN.zip``. Requires no credential. GeoNames data
is CC BY 4.0: credit "GeoNames (geonames.org)" wherever place names are shown.
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
import urllib.request
import zipfile
from pathlib import Path

import pandas as pd
from aeropulse_intelligence.plume.region import GAZETTEER_FILE
from aeropulse_regions import RegionPack
from aeropulse_regions.registry import load_catalog

DOWNLOAD_URL = "https://download.geonames.org/export/dump/{name}.zip"
CACHE_DIR = Path("var/geonames")
#: GeoNames dumps by their population floor, smallest first.
DUMPS: tuple[tuple[int, str], ...] = (
    (500, "cities500"),
    (1000, "cities1000"),
    (5000, "cities5000"),
    (15000, "cities15000"),
)
#: Populated-place codes that are not a place people live in today.
EXCLUDED_FEATURE_CODES = frozenset({"PPLH", "PPLQ", "PPLW", "PPLCH"})
COLUMNS = ["place_id", "name", "lat", "lon", "population", "country_code", "feature_code", "source"]

# GeoNames "geoname" table columns used here (tab separated, no header).
_ID, _NAME, _LAT, _LON, _CLASS, _CODE, _COUNTRY, _POPULATION = 0, 1, 4, 5, 6, 7, 8, 14


def dump_for(min_population: int) -> str:
    """The smallest dump that still holds every place at ``min_population``."""
    fitting = [name for floor, name in DUMPS if floor <= min_population]
    if not fitting:
        raise ValueError(f"no GeoNames dump goes below {DUMPS[0][0]} people")
    return fitting[-1]


def read_dump(path: Path) -> list[list[str]]:
    """Rows of the single ``.txt`` table inside a GeoNames ``citiesN.zip``."""
    with zipfile.ZipFile(path) as archive:
        (member,) = [n for n in archive.namelist() if n.endswith(".txt")]
        with archive.open(member) as raw:
            text = io.TextIOWrapper(raw, encoding="utf-8")
            return list(csv.reader(text, delimiter="\t", quoting=csv.QUOTE_NONE))


def places_for(pack: RegionPack, rows: list[list[str]]) -> pd.DataFrame:
    """The pack's places, most populous first, ties by id."""
    if pack.gazetteer is None:
        raise ValueError(f"{pack.region_id} has no gazetteer section")
    min_lon, min_lat, max_lon, max_lat = pack.geometry.bbox
    countries = set(pack.country_codes)
    kept = []
    for row in rows:
        population = int(row[_POPULATION] or 0)
        lat, lon = float(row[_LAT]), float(row[_LON])
        if (
            row[_CLASS] == "P"
            and row[_CODE] not in EXCLUDED_FEATURE_CODES
            and row[_COUNTRY] in countries
            and population >= pack.gazetteer.min_population
            and min_lon <= lon <= max_lon
            and min_lat <= lat <= max_lat
        ):
            kept.append(
                {
                    "place_id": f"gn_{row[_ID]}",
                    "name": row[_NAME],
                    "lat": lat,
                    "lon": lon,
                    "population": float(population),
                    "country_code": row[_COUNTRY],
                    "feature_code": row[_CODE],
                    "source": "geonames",
                }
            )
    kept.sort(key=lambda p: (-p["population"], p["place_id"]))
    return pd.DataFrame(kept, columns=COLUMNS)


def fetch_dump(name: str) -> Path:
    """The cached dump, downloading it on first use."""
    target = CACHE_DIR / f"{name}.zip"
    if not target.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        url = DOWNLOAD_URL.format(name=name)
        print(f"downloading {url}")
        with urllib.request.urlopen(url, timeout=120) as response:
            target.write_bytes(response.read())
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="build_gazetteer", description="Build gazetteer.parquet from GeoNames."
    )
    parser.add_argument("region_ids", nargs="+")
    parser.add_argument("--config-dir", type=Path, default=None)
    parser.add_argument("--geonames-file", type=Path, default=None, help="a downloaded citiesN.zip")
    args = parser.parse_args(argv)

    catalog = load_catalog(args.config_dir)
    for region_id in args.region_ids:
        pack = catalog.get(region_id)
        if pack.gazetteer is None or pack.gazetteer.source != "geonames":
            print(f"{region_id}: the pack does not name geonames as its gazetteer", file=sys.stderr)
            return 1
        needed = dump_for(pack.gazetteer.min_population)
        if args.geonames_file is not None:
            floor = dict((name, floor) for floor, name in DUMPS).get(args.geonames_file.stem)
            if floor is None or floor > pack.gazetteer.min_population:
                print(
                    f"{region_id}: {args.geonames_file.name} misses places the pack keeps; "
                    f"use {needed}.zip or a smaller dump",
                    file=sys.stderr,
                )
                return 1
        dump = args.geonames_file or fetch_dump(needed)
        places = places_for(pack, read_dump(dump))
        if places.empty:
            print(
                f"{region_id}: no GeoNames place matches the pack; nothing written", file=sys.stderr
            )
            return 1
        target = catalog.region_dir(region_id) / GAZETTEER_FILE
        places.to_parquet(target, index=False)
        top = ", ".join(places["name"].head(5))
        print(f"wrote {target}: {len(places)} places from {dump.name} (largest: {top})")
    print("Place names: GeoNames (geonames.org), CC BY 4.0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
