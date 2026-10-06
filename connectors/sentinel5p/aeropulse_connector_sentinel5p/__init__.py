"""Sentinel-5P NO2/SO2/CO metadata connector (replay)."""

from pathlib import Path

from aeropulse_connector_sdk.raster import RasterFixtureConnector


class Sentinel5PConnector(RasterFixtureConnector):
    """Maps Sentinel-5P product JSON to raster.v1."""

    def __init__(self, fixture_path: Path | None = None) -> None:
        super().__init__(
            metadata_path=Path(__file__).resolve().parent / "metadata.yaml",
            fixture_path=fixture_path,
            source_id="sentinel5p",
            provider="Copernicus",
        )


__all__ = ["Sentinel5PConnector"]
