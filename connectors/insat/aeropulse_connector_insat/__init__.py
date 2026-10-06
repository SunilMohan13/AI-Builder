"""INSAT/MOSDAC replay connector."""

from pathlib import Path

from aeropulse_connector_sdk.geo_asset import GeoAssetConnector


class InsatConnector(GeoAssetConnector):
    """Maps INSAT/MOSDAC inventory JSON to raster.v1 metadata."""

    def __init__(self, fixture_path: Path | None = None) -> None:
        super().__init__(
            metadata_path=Path(__file__).resolve().parent / "metadata.yaml",
            fixture_path=fixture_path,
            source_id="insat",
            provider="INSAT/MOSDAC",
        )


__all__ = ["InsatConnector"]
