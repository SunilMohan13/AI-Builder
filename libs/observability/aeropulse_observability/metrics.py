"""Low-cardinality Prometheus metrics for AeroPulse HTTP services."""

from prometheus_client import Counter, Gauge, Histogram

HTTP_REQUESTS = Counter(
    "aeropulse_http_requests_total",
    "HTTP requests completed",
    ("method", "route", "status"),
)
HTTP_DURATION = Histogram(
    "aeropulse_http_request_duration_seconds",
    "HTTP request duration",
    ("method", "route"),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)
HTTP_IN_FLIGHT = Gauge(
    "aeropulse_http_requests_in_flight",
    "HTTP requests currently executing",
)
CACHE_REQUESTS = Counter(
    "aeropulse_api_cache_requests_total",
    "API response cache outcomes",
    ("route", "outcome"),
)


def route_label(request: object) -> str:
    """Return the matched route template, avoiding IDs in metric labels."""
    scope = getattr(request, "scope", {})
    route = scope.get("route")
    return getattr(route, "path", None) or scope.get("path", "unknown")


# --- Domain metrics (LLD §33.2) -------------------------------------------
#
# HTTP metrics say the API is up; they say nothing about whether the pipeline
# behind it is still producing intelligence. A worker that has silently
# stopped ingesting, or a quality engine rejecting everything, looks perfectly
# healthy from the HTTP side. These are the counters that would show it.
#
# Every label here is bounded: source ids come from `config/sources.yaml`,
# model names from the feature spec, and outcomes from a fixed vocabulary.
# Nothing carries a grid id, an event id or a timestamp, all of which would
# make the cardinality unbounded.

INGESTED_OBSERVATIONS = Counter(
    "aeropulse_observations_ingested_total",
    "Observations processed by the worker, by source and outcome",
    ("source_id", "observation_type", "outcome"),
)
QUALITY_REJECTIONS = Counter(
    "aeropulse_quality_rejections_total",
    "Observations rejected by the quality engine, by failing rule",
    ("source_id", "reason"),
)
QUALITY_SCORE = Histogram(
    "aeropulse_quality_score",
    "Quality score assigned to accepted observations",
    ("source_id",),
    buckets=(0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99, 1.0),
)
FEATURES_MATERIALIZED = Counter(
    "aeropulse_grid_features_materialized_total",
    "Grid-hour feature vectors built by the worker",
)
EVENTS_TRANSITIONED = Counter(
    "aeropulse_events_transitioned_total",
    "Pollution event state transitions, by resulting status and severity",
    ("status", "severity"),
)
ML_INFERENCE_DURATION = Histogram(
    "aeropulse_ml_inference_duration_seconds",
    "Model inference latency, excluding feature construction",
    ("model_name",),
    buckets=(0.0005, 0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0),
)
ML_PREDICTIONS = Counter(
    "aeropulse_ml_predictions_total",
    "Model predictions attempted, by family and outcome",
    ("model_name", "outcome"),
)
SHADOW_PREDICTIONS = Counter(
    "aeropulse_shadow_predictions_total",
    "Challenger predictions recorded in shadow, by family and outcome",
    ("model_name", "outcome"),
)
MODEL_FEATURE_COMPLETENESS = Histogram(
    "aeropulse_model_feature_completeness",
    "Fraction of a model's input vector that was populated at prediction time",
    ("model_name",),
    buckets=(0.25, 0.5, 0.75, 0.9, 0.95, 0.99, 1.0),
)
