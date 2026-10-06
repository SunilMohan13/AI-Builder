"""Build training frames from canonical observations.

Every column here is produced by the *serving* feature builder
(:func:`aeropulse_intelligence.features.build_features`) and projected through
the shared :mod:`aeropulse_contracts.feature_spec`. Training therefore cannot
see a feature that online inference will not have, which is the failure this
module exists to prevent.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
from aeropulse_contracts.feature import FEATURE_VERSION, GridFeature
from aeropulse_contracts.feature_spec import ML_FEATURE_VERSION, to_feature_dict
from aeropulse_contracts.meteo import MeteorologicalObservation
from aeropulse_contracts.observation import Observation
from aeropulse_contracts.raster import RasterObservation
from aeropulse_geospatial.grid import to_grid_id
from aeropulse_intelligence.features import build_features, hour_bucket
from aeropulse_intelligence.snapshot import FeatureSnapshot

#: Identity and bookkeeping columns carried alongside the model features.
INDEX_COLUMNS = ("grid_id", "timestamp", "feature_version", "ml_feature_version")


@dataclass(frozen=True)
class DatasetMetadata:
    """Provenance for one materialised training frame.

    Attributes:
        rows: Number of grid-hour rows.
        grid_cells: Distinct H3 cells represented.
        start: Earliest feature timestamp.
        end: Latest feature timestamp.
        feature_version: Serving feature contract version.
        ml_feature_version: Shared ML feature spec version.
        sources: Source ids that contributed observations.
    """

    rows: int
    grid_cells: int
    start: datetime | None
    end: datetime | None
    feature_version: str
    ml_feature_version: str
    sources: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable view for artifact metadata."""
        return {
            "rows": self.rows,
            "grid_cells": self.grid_cells,
            "start": self.start.isoformat() if self.start else None,
            "end": self.end.isoformat() if self.end else None,
            "feature_version": self.feature_version,
            "ml_feature_version": self.ml_feature_version,
            "sources": list(self.sources),
        }


def _cell_centre(observations: Sequence[Observation]) -> tuple[float, float]:
    """Return the mean location of a cell's observations."""
    lat = sum(o.location.lat for o in observations) / len(observations)
    lon = sum(o.location.lon for o in observations) / len(observations)
    return lat, lon


def build_grid_features(
    air_quality: Iterable[Observation],
    weather: Iterable[MeteorologicalObservation],
    fires: Iterable[Any] = (),
    rasters: Iterable[Any] = (),
) -> list[GridFeature]:
    """Materialise one :class:`GridFeature` per observed grid-hour.

    The full observation set is handed to every call so that lag and rolling
    windows can look backwards. Those windows are computed by the serving code
    and already exclude the current hour, so this is not a leakage channel.

    Args:
        air_quality: Canonical air-quality observations.
        weather: Canonical meteorological observations.
        fires: Canonical fire observations, when available.
        rasters: Canonical raster/satellite samples, when available.

    Returns:
        Grid-hour features sorted by cell then timestamp.
    """
    aq = list(air_quality)
    wx = list(weather)
    fire_list = list(fires)
    raster_list = list(rasters)
    for obs in aq:
        if obs.grid_id is None:
            obs.grid_id = to_grid_id(obs.location.lat, obs.location.lon)

    snapshot = FeatureSnapshot(
        air_quality=aq,
        weather=wx,
        fires=fire_list,
        rasters=raster_list,
    )

    by_cell: dict[str, list[Observation]] = {}
    for obs in aq:
        by_cell.setdefault(str(obs.grid_id), []).append(obs)

    features: list[GridFeature] = []
    for grid_id, cell_observations in by_cell.items():
        lat, lon = _cell_centre(cell_observations)
        hours = sorted({hour_bucket(o.observed_at) for o in cell_observations})
        for hour in hours:
            features.append(
                build_features(
                    grid_id,
                    hour,
                    snapshot,
                    center_lat=lat,
                    center_lon=lon,
                )
            )
    features.sort(key=lambda f: (f.grid_id, f.timestamp))
    return features


def features_to_frame(features: Sequence[GridFeature]) -> pd.DataFrame:
    """Project grid features into a dataframe via the shared feature spec.

    Args:
        features: Materialised grid-hour features.

    Returns:
        One row per grid-hour, with identity columns plus every feature the
        shared spec can derive. Column names match the spec exactly.
    """
    rows: list[dict[str, Any]] = []
    for feature in features:
        row: dict[str, Any] = {
            "grid_id": feature.grid_id,
            "timestamp": feature.timestamp,
            "feature_version": feature.feature_version,
            "ml_feature_version": ML_FEATURE_VERSION,
        }
        row.update(to_feature_dict(feature))
        rows.append(row)
    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
        frame = frame.sort_values(["grid_id", "timestamp"]).reset_index(drop=True)
    return frame


def describe(frame: pd.DataFrame, sources: Sequence[str]) -> DatasetMetadata:
    """Summarise a training frame for artifact provenance.

    Args:
        frame: Materialised training frame.
        sources: Source ids that contributed observations.

    Returns:
        Dataset metadata.
    """
    if frame.empty:
        return DatasetMetadata(
            rows=0,
            grid_cells=0,
            start=None,
            end=None,
            feature_version=FEATURE_VERSION,
            ml_feature_version=ML_FEATURE_VERSION,
            sources=tuple(sources),
        )
    return DatasetMetadata(
        rows=len(frame),
        grid_cells=int(frame["grid_id"].nunique()),
        start=frame["timestamp"].min().to_pydatetime(),
        end=frame["timestamp"].max().to_pydatetime(),
        feature_version=str(frame["feature_version"].iloc[0]),
        ml_feature_version=str(frame["ml_feature_version"].iloc[0]),
        sources=tuple(sources),
    )


def save_parquet(frame: pd.DataFrame, path: Path) -> Path:
    """Persist a training frame, falling back to CSV without pyarrow.

    Offline datasets belong in object storage as Parquet per LLD §20; the CSV
    fallback keeps the pipeline runnable in a minimal environment.

    Args:
        frame: Frame to write.
        path: Target path ending in ``.parquet``.

    Returns:
        The path actually written.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        frame.to_parquet(path, index=False)
        return path
    except (ImportError, ValueError):
        fallback = path.with_suffix(".csv")
        frame.to_csv(fallback, index=False)
        return fallback


def load_observations_from_openmeteo(
    fixture_path: Path | None = None,
    *,
    live: bool = False,
    days: int = 2,
    sites: Sequence[dict[str, Any]] | None = None,
) -> tuple[list[Observation], list[MeteorologicalObservation], list[RasterObservation]]:
    """Load canonical observations from the Open-Meteo connector.

    This is the credential-free training source. It returns canonical contracts
    rather than raw payloads, so the same records could equally have come from
    CPCB or IMD.

    Args:
        fixture_path: Replay fixture. Defaults to the committed fixture.
        live: Request a live fetch. Requires ``AEROPULSE_CONNECTOR_MODE=live``.
        days: Trailing days of history to request in live mode.
        sites: Override the connector's default corridor sites.

    Returns:
        ``(air_quality, weather, rasters)`` canonical observations.
    """
    from aeropulse_connector_openmeteo import OpenMeteoConnector
    from aeropulse_connector_sdk.contracts import FetchRequest

    default_fixture = Path("fixtures/openmeteo/observations.json")
    connector = OpenMeteoConnector(
        fixture_path or default_fixture,
        sites=sites,
        past_days=days,
    )
    request = FetchRequest()
    if live:
        end = datetime.now(UTC)
        request = FetchRequest(start_time=end - timedelta(days=days), end_time=end)

    air_quality: list[Observation] = []
    weather: list[MeteorologicalObservation] = []
    rasters: list[RasterObservation] = []
    for record in connector.fetch(request):
        for item in connector.normalize(record):
            if isinstance(item, Observation):
                air_quality.append(item)
            elif isinstance(item, MeteorologicalObservation):
                weather.append(item)
            elif isinstance(item, RasterObservation):
                rasters.append(item)
    return air_quality, weather, rasters


def write_metadata(metadata: DatasetMetadata, path: Path) -> Path:
    """Write dataset provenance next to its artifact.

    Args:
        metadata: Dataset summary.
        path: Target JSON path.

    Returns:
        The written path.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(metadata.to_dict(), indent=2) + "\n", encoding="utf-8")
    return path
