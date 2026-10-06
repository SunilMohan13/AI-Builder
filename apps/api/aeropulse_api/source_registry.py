"""Build the source registry from yaml + SOURCE_SPECS.

``GET /api/v1/sources`` used to be a parallel 7-row dict that listed IMD as
enabled, omitted OpenAQ/Open-Meteo, and never joined connector health. This
module is the single list: yaml owns ``enabled`` / ``interval_seconds`` /
``live_capable``, ``SOURCE_SPECS`` owns the runner identity, and display
fields fill in names the yaml does not carry.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from aeropulse_connector_app.registry import SPECS_BY_ID, SourceSpec

# Human-facing fields yaml does not carry. Not the source of truth for
# enabled/live_capable — those come from config/sources.yaml and SourceSpec.
_DISPLAY: dict[str, dict[str, str]] = {
    "cpcb": {
        "provider": "CPCB",
        "display_name": "CPCB CAAQMS",
        "data_type": "air_quality",
        "schema_version": "observation.v1",
    },
    "openaq": {
        "provider": "OpenAQ",
        "display_name": "OpenAQ (CPCB CAAQMS)",
        "data_type": "air_quality",
        "schema_version": "observation.v1",
    },
    "firms": {
        "provider": "NASA",
        "display_name": "NASA FIRMS VIIRS",
        "data_type": "active_fire",
        "schema_version": "fire_observation.v1",
    },
    "imd": {
        "provider": "IMD",
        "display_name": "IMD Weather",
        "data_type": "weather",
        "schema_version": "meteo.v1",
    },
    "openmeteo": {
        "provider": "Open-Meteo",
        "display_name": "Open-Meteo",
        "data_type": "air_quality",
        "schema_version": "observation.v1",
    },
    "sentinel5p": {
        "provider": "Copernicus",
        "display_name": "Sentinel-5P",
        "data_type": "satellite_gas",
        "schema_version": "raster.v1",
    },
    "modis": {
        "provider": "NASA",
        "display_name": "MODIS MAIAC AOD",
        "data_type": "aod",
        "schema_version": "raster.v1",
    },
    "cams": {
        "provider": "ECMWF",
        "display_name": "CAMS composition",
        "data_type": "composition_forecast",
        "schema_version": "raster.v1",
    },
    "insat": {
        "provider": "ISRO",
        "display_name": "INSAT-3D",
        "data_type": "satellite",
        "schema_version": "raster.v1",
    },
    "bhuvan": {
        "provider": "ISRO",
        "display_name": "Bhuvan",
        "data_type": "land_cover",
        "schema_version": "raster.v1",
    },
    "icar": {
        "provider": "ICAR",
        "display_name": "ICAR crop residue",
        "data_type": "agriculture",
        "schema_version": "raster.v1",
    },
    "industry": {
        "provider": "Industry",
        "display_name": "Industry OCEMS",
        "data_type": "emissions",
        "schema_version": "raster.v1",
    },
    "osm": {
        "provider": "OpenStreetMap",
        "display_name": "OSM roads and industry",
        "data_type": "geo_asset",
        "schema_version": "raster.v1",
    },
    "population": {
        "provider": "Reference fixture / WorldPop-compatible adapter",
        "display_name": "Population density",
        "data_type": "population_density",
        "schema_version": "population-density.v1",
    },
}


def repo_root() -> Path:
    """Return the project root for fixture-backed connector health checks."""
    for candidate in (Path("/app"), Path(".")):
        if (candidate / "fixtures").exists() and (candidate / "config" / "sources.yaml").exists():
            return candidate
    return Path(".")


def sources_config_path() -> Path:
    """Path to the load-bearing source registry."""
    return repo_root() / "config" / "sources.yaml"


def load_yaml_sources(config_path: Path | None = None) -> list[dict[str, Any]]:
    """Parse ``config/sources.yaml`` into raw rows.

    Args:
        config_path: Override used by tests.

    Returns:
        The ``sources`` list, or empty if the file is missing or malformed.
    """
    path = config_path or sources_config_path()
    try:
        raw = yaml.safe_load(path.read_text()) if path.exists() else {}
    except (OSError, yaml.YAMLError):
        return []
    sources = (raw or {}).get("sources", []) if isinstance(raw, dict) else []
    return [row for row in sources if isinstance(row, dict) and row.get("id")]


def registry_items(config_path: Path | None = None) -> list[dict[str, Any]]:
    """Return one registry dict per yaml source, joined with SourceSpec.

    Population has no connector spec and is still listed: it is a reference
    layer the risk endpoint reads, not an ingested stream.
    """
    items: list[dict[str, Any]] = []
    for row in load_yaml_sources(config_path):
        source_id = str(row["id"])
        spec: SourceSpec | None = SPECS_BY_ID.get(source_id)
        display = _DISPLAY.get(source_id, {})
        live_capable = (
            spec.live_capable if spec is not None else bool(row.get("live_capable", False))
        )
        items.append(
            {
                "source_id": source_id,
                "provider": display.get("provider", source_id),
                "connector_id": str(row.get("connector") or source_id),
                "display_name": display.get("display_name", source_id),
                "data_type": display.get("data_type", "unknown"),
                "enabled": bool(row.get("enabled", True)),
                "live_capable": live_capable,
                "interval_seconds": int(row.get("interval_seconds") or 0) or None,
                "status": "registered",
                "schema_version": display.get("schema_version", ""),
            }
        )
    return items


def registry_by_id(config_path: Path | None = None) -> dict[str, dict[str, Any]]:
    """Index :func:`registry_items` by source id."""
    return {item["source_id"]: item for item in registry_items(config_path)}
