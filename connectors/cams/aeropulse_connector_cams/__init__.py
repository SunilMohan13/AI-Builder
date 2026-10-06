"""CAMS background composition connector (replay)."""

from pathlib import Path

from aeropulse_connector_sdk.raster import RasterFixtureConnector


class CamsConnector(RasterFixtureConnector):
    """Maps CAMS product JSON to raster.v1."""

    def __init__(self, fixture_path: Path | None = None) -> None:
        super().__init__(
            metadata_path=Path(__file__).resolve().parent / "metadata.yaml",
            fixture_path=fixture_path,
            source_id="cams",
            provider="ECMWF",
        )


__all__ = ["CamsConnector"]
