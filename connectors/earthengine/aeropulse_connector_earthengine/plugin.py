"""Earth Engine plugin: daily Sentinel-5P UV aerosol index per coarse H3 cell.

Live needs the ``earthengine-api`` package, ``AEROPULSE_EARTHENGINE_PROJECT``
and Application Default Credentials; any of them missing reports "not
configured" with zero records. The reduction runs server-side over the
pack's wind-site cells (coarse H3 over the source domain), so the source
domain is never tiled at resolution 8. A cloudy cell is missing, not zero:
its ``valid_pixel_fraction`` says how much of it was seen.

Replay reads a region-specific fixture of already-reduced cells::

    {"product": "s5p_aer_ai", "date": "YYYY-MM-DD",
     "cells": [{"cell": "<h3>", "mean": <float|null>, "valid_fraction": <0..1>}]}
"""

from __future__ import annotations

import importlib
from datetime import UTC, date, datetime, timedelta
from typing import Any

import h3
from aeropulse_common.ids import new_ulid
from aeropulse_common.settings import Settings, get_settings
from aeropulse_connector_sdk.contracts import RawRecord
from aeropulse_connector_sdk.plugin import BasePlugin, ConnectorContext, ConnectorResult
from aeropulse_connector_sdk.testing import load_fixture
from aeropulse_contracts import (
    CanonicalRecord,
    Provenance,
    ProvenanceClass,
    Quality,
    RasterObservation,
)
from aeropulse_observability.logging import get_logger

logger = get_logger("aeropulse.connector.earthengine")

SOURCE_ID = "earthengine"
CONNECTOR_VERSION = "0.1.0"

#: Product key -> (Earth Engine collection, band).
PRODUCTS: dict[str, tuple[str, str]] = {
    "s5p_aer_ai": ("COPERNICUS/S5P/NRTI/L3_AER_AI", "absorbing_aerosol_index"),
}
#: Nominal L3 grid scale of the S5P NRTI products in metres.
S5P_SCALE_M = 1113.2


def _ee_module() -> Any | None:
    try:
        return importlib.import_module("ee")
    except ImportError:
        return None


class EarthEnginePlugin(BasePlugin):
    source_id = SOURCE_ID
    supported_contracts = frozenset({"raster.v1"})
    #: A satellite retrieval of the aerosol index itself, not surface PM2.5.
    provenance_class = ProvenanceClass.MEASURED

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings

    @property
    def project(self) -> str | None:
        return (self._settings or get_settings()).earthengine_project

    def configuration_issue(self, context: ConnectorContext) -> str | None:
        if not context.is_network:
            return super().configuration_issue(context)
        if _ee_module() is None:
            return "earthengine-api is not installed (install the 'live' extra)"
        if not self.project:
            return "AEROPULSE_EARTHENGINE_PROJECT is not set"
        if not context.sites:
            return f"no sites placed for {context.region_id}"
        unknown = [p for p in self._products(context) if p not in PRODUCTS]
        if unknown:
            return f"unknown Earth Engine products: {unknown}"
        return None

    def _products(self, context: ConnectorContext) -> list[str]:
        return [str(p) for p in (context.param("products") or ["s5p_aer_ai"])]

    def fetch(self, context: ConnectorContext) -> ConnectorResult:
        if not context.is_network:
            assert context.fixture_path is not None
            payload = load_fixture(context.fixture_path)
            record = RawRecord(
                source_id=SOURCE_ID,
                source_record_id=f"{payload['product']}_{payload['date']}",
                payload=payload,
                fetched_at=context.now,
            )
            return ConnectorResult(source_id=SOURCE_ID, records=[record], fetched_at=context.now)

        day = (context.now - timedelta(days=1)).date()
        records = [
            RawRecord(
                source_id=SOURCE_ID,
                source_record_id=f"{product}_{day.isoformat()}",
                payload=self._reduce(product, day, context),
                fetched_at=datetime.now(UTC),
            )
            for product in self._products(context)
        ]
        return ConnectorResult(source_id=SOURCE_ID, records=records, fetched_at=context.now)

    def _reduce(self, product: str, day: date, context: ConnectorContext) -> dict[str, Any]:
        ee = _ee_module()
        assert ee is not None
        ee.Initialize(project=self.project)
        collection, band = PRODUCTS[product]
        start = day.isoformat()
        end = (day + timedelta(days=1)).isoformat()
        image = ee.ImageCollection(collection).select(band).filterDate(start, end).mean()
        features = []
        for site in context.sites:
            ring = [[lon, lat] for lat, lon in h3.cell_to_boundary(site.site_id)]
            features.append(
                ee.Feature(ee.Geometry.Polygon([[*ring, ring[0]]]), {"cell": site.site_id})
            )
        reducer = ee.Reducer.mean().combine(ee.Reducer.count(), sharedInputs=True)
        seen = image.reduceRegions(ee.FeatureCollection(features), reducer, S5P_SCALE_M)
        total = image.unmask(0).reduceRegions(
            ee.FeatureCollection(features), ee.Reducer.count(), S5P_SCALE_M
        )
        seen_info = seen.getInfo()["features"]
        total_by_cell = {
            f["properties"]["cell"]: f["properties"].get("count") or 0
            for f in total.getInfo()["features"]
        }
        cells = []
        for feature in seen_info:
            props = feature["properties"]
            cell = props["cell"]
            expected = total_by_cell.get(cell) or 0
            count = props.get("count") or 0
            cells.append(
                {
                    "cell": cell,
                    "mean": props.get("mean"),
                    "valid_fraction": (count / expected) if expected else 0.0,
                }
            )
        return {"product": product, "date": day.isoformat(), "cells": cells}

    def normalize(
        self, result: ConnectorResult, context: ConnectorContext
    ) -> list[CanonicalRecord]:
        out: list[CanonicalRecord] = []
        for record in result.records:
            payload = record.payload
            product = str(payload["product"])
            day = datetime.fromisoformat(str(payload["date"])).replace(tzinfo=UTC)
            for cell in payload.get("cells", []):
                cell_id = str(cell["cell"])
                lat, lon = h3.cell_to_latlng(cell_id)
                mean = cell.get("mean")
                fraction = float(cell.get("valid_fraction") or 0.0)
                out.append(
                    RasterObservation(
                        observation_id=new_ulid("ras"),
                        source_id=SOURCE_ID,
                        source_record_id=f"{product}_{payload['date']}_{cell_id}",
                        product_id=product,
                        acquisition_time=day,
                        processing_time=record.fetched_at,
                        bbox=(lon, lat, lon, lat),
                        resolution=f"h3r{h3.get_resolution(cell_id)}",
                        object_uri=record.raw_uri or "",
                        checksum="",
                        quality=Quality(
                            quality_flag="valid" if mean is not None else "missing",
                            quality_score=max(0.0, min(1.0, fraction)),
                        ),
                        provenance=Provenance(
                            provider="Copernicus Sentinel-5P via Google Earth Engine",
                            connector_version=CONNECTOR_VERSION,
                            raw_object_uri=record.raw_uri,
                        ),
                        sample_aerosol_index=None if mean is None else float(mean),
                        valid_pixel_fraction=max(0.0, min(1.0, fraction)),
                        grid_id=cell_id,
                    )
                )
        return out
