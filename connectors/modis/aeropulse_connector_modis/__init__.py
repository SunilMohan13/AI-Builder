"""MODIS MAIAC AOD metadata connector (replay). AOD is not surface PM2.5."""

from pathlib import Path

from aeropulse_connector_sdk.raster import RasterFixtureConnector


class ModisConnector(RasterFixtureConnector):
    """Maps MODIS AOD product JSON to raster.v1."""

    def __init__(self, fixture_path: Path | None = None) -> None:
        super().__init__(
            metadata_path=Path(__file__).resolve().parent / "metadata.yaml",
            fixture_path=fixture_path,
            source_id="modis",
            provider="NASA",
        )


__all__ = ["ModisConnector"]
