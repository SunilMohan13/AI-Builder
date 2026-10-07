"""Canonical raster observation metadata (raster.v1).

Large arrays are stored in object storage, never Kafka or TimescaleDB.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from aeropulse_contracts.observation import Provenance, Quality


class RasterObservation(BaseModel):
    """Metadata for a satellite/raster product stored in MinIO/S3."""

    model_config = {"extra": "forbid"}

    observation_id: str
    source_id: str
    source_record_id: str
    schema_version: Literal["raster.v1"] = "raster.v1"
    product_id: str
    acquisition_time: datetime
    processing_time: datetime
    bbox: tuple[float, float, float, float] = Field(
        ..., description="min_lon, min_lat, max_lon, max_lat"
    )
    crs: str = "EPSG:4326"
    resolution: str
    object_uri: str
    checksum: str
    cloud_fraction: float | None = Field(default=None, ge=0.0, le=1.0)
    quality: Quality
    provenance: Provenance
    sample_aod: float | None = None
    sample_no2: float | None = None
    sample_pm25: float | None = None
    #: Sentinel-5P UV aerosol index (unitless) and the share of valid pixels in
    #: the reduction. A cloudy cell is missing, not zero.
    sample_aerosol_index: float | None = None
    valid_pixel_fraction: float | None = Field(default=None, ge=0.0, le=1.0)
    region_id: str | None = None
    #: Set when the raster value is reduced to one H3 cell, so a blend can be
    #: located to the cell instead of taking "the last raster anywhere".
    grid_id: str | None = None
