"""Kafka topic names the connector publishes and the worker consumes.

Earlier designs named a topic for every pipeline stage (quality, normalize,
events, alerts). This build persists inside the worker, so only the
observation topics and the meteorology forecast topic exist.
"""

OBSERVATION_AQ = "aero.observation.air_quality"
OBSERVATION_FIRE = "aero.observation.fire"
OBSERVATION_WEATHER = "aero.observation.weather"
METEO_FORECAST = "aero.meteo.forecast"
OBSERVATION_RASTER = "aero.observation.raster"
