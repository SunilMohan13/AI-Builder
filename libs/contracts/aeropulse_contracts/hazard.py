"""Hazard and peak forecast contracts (hazard.v1, peak_forecast.v1).

These carry the outputs of the two 24-hour models added in integration plan
Phases 1-3. Both follow the existing conventions: ``extra: forbid``, an
explicit ``schema_version``, and a ``model_version`` on every payload.

Three fields exist specifically to stop a reader over-trusting the number
next to them, and none of them is optional decoration:

* ``degraded`` says the answer came from the deterministic fallback rather
  than a trained model, so a baseline can never be mistaken for a prediction.
* ``calibrated`` says whether a hazard score may be read as a probability. An
  uncalibrated gradient-boosting score ranks hours correctly but its magnitude
  is not a frequency, and presenting 0.8 as "80% chance" would be wrong.
* ``feature_completeness`` says how much of the input vector was actually
  populated, because a tree model returns a confident answer from a vector of
  nulls rather than an error.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

HAZARD_SCHEMA_VERSION = "hazard.v1"
PEAK_FORECAST_SCHEMA_VERSION = "peak_forecast.v1"

#: CPCB National AQI "Very Poor" lower breakpoint for PM2.5 (ug/m3). The single
#: reconciled hazard threshold: the pm25 research pipeline used 150 and the
#: anomaly pipeline 121, and serving both would put two contradictory hazard
#: probabilities on one map cell. 121 wins because it is the national standard
#: and this is a public-facing alert.
HAZARD_THRESHOLD_UGM3 = 121.0

#: Deterministic fallback served while no hazard model is promoted. Named so
#: that a consumer reading `model_version` can tell at a glance that no model
#: was involved.
HAZARD_BASELINE_VERSION = "persistence-hazard-0.1"

#: Deterministic fallback for the peak forecast: today's value, carried
#: forward. It is a weak predictor and is labelled as one.
PEAK_BASELINE_VERSION = "persistence-peak-0.1"


class HazardCell(BaseModel):
    """Probability that one cell reaches the hazard threshold within a horizon."""

    model_config = {"extra": "forbid"}

    schema_version: Literal["hazard.v1"] = "hazard.v1"
    grid_id: str
    timestamp: datetime
    center_lat: float | None = None
    center_lon: float | None = None

    hazard_score: float = Field(..., ge=0.0, le=1.0)
    threshold_ugm3: float = HAZARD_THRESHOLD_UGM3
    horizon_hours: int = 24

    #: False when the score comes from an uncalibrated classifier. Such a score
    #: orders cells correctly but is not a probability, and the UI must not
    #: render it as a percentage.
    calibrated: bool = False
    #: True when this is the deterministic fallback, not a trained model.
    degraded: bool = True
    model_version: str = HAZARD_BASELINE_VERSION
    feature_version: str | None = None
    #: Fraction of the model's inputs that were populated, or None for the
    #: deterministic path which consumes a single observation.
    feature_completeness: float | None = Field(default=None, ge=0.0, le=1.0)
    observed_pm25: float | None = None


class PeakForecast(BaseModel):
    """Maximum PM2.5 expected for one cell over a forward window."""

    model_config = {"extra": "forbid"}

    schema_version: Literal["peak_forecast.v1"] = "peak_forecast.v1"
    grid_id: str
    timestamp: datetime
    center_lat: float | None = None
    center_lon: float | None = None

    peak_pm25: float
    #: Interval from the training residual spread, absent on the deterministic
    #: path where no residual distribution exists.
    prediction_interval_low: float | None = None
    prediction_interval_high: float | None = None
    horizon_hours: int = 24

    exceeds_threshold: bool = False
    threshold_ugm3: float = HAZARD_THRESHOLD_UGM3
    degraded: bool = True
    model_version: str = PEAK_BASELINE_VERSION
    feature_version: str | None = None
    feature_completeness: float | None = Field(default=None, ge=0.0, le=1.0)
    observed_pm25: float | None = None
