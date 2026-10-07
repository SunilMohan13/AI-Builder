"""Family name -> plugin. Adding a family is one entry here."""

from __future__ import annotations

from collections.abc import Callable

from aeropulse_common.errors import TrainingError
from aeropulse_regions import RegionCatalog

from aeropulse_ml.models.anomaly import AnomalyPlugin
from aeropulse_ml.models.base import ModelPlugin
from aeropulse_ml.models.forecast import Pm25ForecastPlugin
from aeropulse_ml.models.hazard import Pm25Hazard24hPlugin
from aeropulse_ml.models.source_likelihood import SourceLikelihoodPlugin

PLUGINS: dict[str, Callable[[RegionCatalog], ModelPlugin]] = {
    "pm25_forecast": lambda catalog: Pm25ForecastPlugin(),
    "pm25_hazard_24h": lambda catalog: Pm25Hazard24hPlugin(),
    "anomaly": lambda catalog: AnomalyPlugin(),
    "source_likelihood": SourceLikelihoodPlugin,
}


def get_plugin(family: str, catalog: RegionCatalog) -> ModelPlugin:
    try:
        factory = PLUGINS[family]
    except KeyError as exc:
        raise TrainingError(f"unknown model family: {family!r}; known: {sorted(PLUGINS)}") from exc
    return factory(catalog)
