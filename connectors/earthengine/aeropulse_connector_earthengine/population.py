"""WorldPop population per H3 cell, for onboarding (LLD APAC 4.5 step 5).

Run once per region by ``aeropulse-region init --population``; the result is
written to the pack directory as ``population_h3r8.json`` with the WorldPop
year, and is the only population the plume exposure estimate may use.
"""

from __future__ import annotations

import importlib
from collections.abc import Sequence
from typing import Any

import h3
from aeropulse_common.errors import ConnectorError

WORLDPOP_COLLECTION = "WorldPop/GP/100m/pop"
WORLDPOP_SCALE_M = 100
_BATCH = 500


def population_by_cell(
    cells: Sequence[str],
    *,
    country_codes: Sequence[str],
    year: int,
    project: str,
) -> dict[str, float]:
    """Sum WorldPop people inside each H3 cell.

    Args:
        cells: H3 cell ids (any resolution).
        country_codes: ISO alpha-2 codes; WorldPop is filtered by ISO alpha-3
            derived server-side from the ``country`` property.
        year: WorldPop year.
        project: Earth Engine project id.

    Raises:
        ConnectorError: ``earthengine-api`` is not installed.
    """
    try:
        ee: Any = importlib.import_module("ee")
    except ImportError as exc:
        raise ConnectorError("earthengine-api is not installed") from exc
    ee.Initialize(project=project)
    image = (
        ee.ImageCollection(WORLDPOP_COLLECTION)
        .filter(ee.Filter.eq("year", year))
        .filter(ee.Filter.inList("country", [_alpha3(c) for c in country_codes]))
        .mosaic()
    )
    out: dict[str, float] = {}
    for start in range(0, len(cells), _BATCH):
        batch = cells[start : start + _BATCH]
        features = []
        for cell in batch:
            ring = [[lon, lat] for lat, lon in h3.cell_to_boundary(cell)]
            features.append(ee.Feature(ee.Geometry.Polygon([[*ring, ring[0]]]), {"cell": cell}))
        reduced = image.reduceRegions(
            ee.FeatureCollection(features), ee.Reducer.sum(), WORLDPOP_SCALE_M
        ).getInfo()
        for feature in reduced["features"]:
            props = feature["properties"]
            out[props["cell"]] = float(props.get("sum") or 0.0)
    return out


_ALPHA3 = {"IN": "IND", "SG": "SGP", "AU": "AUS", "MY": "MYS", "ID": "IDN", "BN": "BRN"}


def _alpha3(code: str) -> str:
    try:
        return _ALPHA3[code]
    except KeyError as exc:
        raise ConnectorError(f"no ISO alpha-3 mapping for {code}; add it to _ALPHA3") from exc
