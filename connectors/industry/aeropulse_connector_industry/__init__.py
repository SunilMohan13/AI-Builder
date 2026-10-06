"""Industry/OCEMS replay connector."""

from pathlib import Path

from aeropulse_connector_sdk.geo_asset import GeoAssetConnector


class IndustryConnector(GeoAssetConnector):
    """Maps Industry/OCEMS inventory JSON to raster.v1 metadata."""

    def __init__(self, fixture_path: Path | None = None) -> None:
        super().__init__(
            metadata_path=Path(__file__).resolve().parent / "metadata.yaml",
            fixture_path=fixture_path,
            source_id="industry",
            provider="Industry/OCEMS",
        )


__all__ = ["IndustryConnector"]
