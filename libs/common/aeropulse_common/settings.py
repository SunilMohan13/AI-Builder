"""Environment-backed application settings.

Secrets are referenced by name only. Never log field values marked as secret.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Environments where the built-in development JWT secret is tolerated.
DEV_ENVIRONMENTS = frozenset({"development", "dev", "local", "test"})
_DEV_JWT_SECRET = "dev-only-change-me-use-32-bytes-min"
_MIN_JWT_SECRET_BYTES = 32


class Settings(BaseSettings):
    """Runtime configuration loaded from ``AEROPULSE_`` environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="AEROPULSE_",
        env_file=".env",
        extra="ignore",
    )

    service_name: str = "aeropulse"
    service_version: str = "0.1.0"
    environment: str = "development"
    log_level: str = "INFO"

    jwt_secret: SecretStr = Field(default=SecretStr(_DEV_JWT_SECRET))
    jwt_algorithm: str = "HS256"
    jwt_issuer: str = "aeropulse"
    # The only CORS allow-list: comma-separated origins plus one optional
    # regex (Netlify and Render mint a subdomain per deploy). Unset the regex
    # with AEROPULSE_CORS_ORIGIN_REGEX="" to allow the listed origins only.
    cors_origins: str = (
        "http://127.0.0.1:5173,http://localhost:5173,http://127.0.0.1:4173,"
        "http://localhost:4173,https://aeropulse-india.netlify.app"
    )
    cors_origin_regex: str = r"https://[a-z0-9-]+\.(?:netlify\.app|onrender\.com)"

    # Local Compose defaults only. Override via AEROPULSE_* in every non-dev env.
    database_url: str | None = Field(
        default=None,
        description="Set AEROPULSE_DATABASE_URL (include password). Compose injects it.",
    )
    redis_url: str = "redis://127.0.0.1:6379/0"
    kafka_bootstrap_servers: str = "127.0.0.1:19092"
    minio_endpoint: str = "127.0.0.1:9000"
    minio_access_key: SecretStr | None = None
    minio_secret_key: SecretStr | None = None
    minio_bucket: str = "aeropulse"
    minio_secure: bool = False

    otel_exporter_otlp_endpoint: str | None = None
    connector_mode: Literal["replay", "live"] = "replay"
    default_h3_resolution: int = 8

    # Live-source credentials. Both are free to obtain; absence means the
    # source reports NOT_CONFIGURED rather than silently replaying a fixture.
    firms_map_key: SecretStr | None = None
    openaq_api_key: SecretStr | None = None
    # Upstreams backfill late-arriving data, so a live fetch rewinds this far
    # behind its watermark. Safe only because the worker dedups on dedup_key.
    connector_watermark_overlap_seconds: int = Field(default=3600, ge=0)
    # `/latest`-style endpoints happily return values from long-dead stations.
    connector_max_observation_age_hours: int = Field(default=6, ge=1)
    connector_default_interval_seconds: int = Field(default=3600, ge=60)
    # Dry-run switch. "stdout" prints envelopes instead of publishing them;
    # it is never a failure fallback, only an explicit operator choice.
    connector_publish: Literal["kafka", "stdout"] = "kafka"
    # Gemini powers the copilot only. The event path stays deterministic.
    # Server-side only: never expose this to the browser bundle.
    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-3.8-flash"
    copilot_prompt_version: str = "v2"

    oidc_jwks_url: str | None = None
    # Algorithms accepted from the OIDC issuer. Pinned so a token cannot pick
    # its own algorithm.
    oidc_algorithms: str = "RS256"

    # Region Packs, hazard profiles, AQI standards, model_serving.yaml.
    config_dir: Path = Path("config")
    # "local" uses Parquet + filesystem/MinIO stores; "gcp" uses BigQuery + GCS.
    platform: Literal["local", "gcp"] = "local"
    default_region: str = "in-north"
    # Root for the local Parquet analytics store, snapshots, and artifacts.
    data_dir: Path = Path("var/aeropulse")
    # Local object store: plain files under data_dir, or the Compose MinIO.
    local_object_store: Literal["filesystem", "minio"] = "filesystem"
    gcp_project: str | None = None
    # Bucket name prefix; buckets are "<prefix>-raw", "-citizen", "-models",
    # "-serving". Defaults to "<gcp_project>-aeropulse".
    gcs_bucket: str | None = None
    # BigQuery dataset prefix; datasets are "<prefix>_raw", "_predictions", ...
    bigquery_dataset: str = "aeropulse"
    # Ceiling on bytes one templated BigQuery query may bill.
    bigquery_max_bytes: int = Field(default=1_000_000_000, ge=1)
    earthengine_project: str | None = None
    # Vision model for citizen photos (AI visual observation only).
    citizen_vision_model: str = "gemini-3.8-flash"
    # HMAC key for reporter identity hashes. Required outside development;
    # in development a per-process random key is used, so hashes (and the
    # per-reporter rate limit) reset on restart.
    citizen_reporter_salt: SecretStr | None = None
    # Base URL of the citizen analyzer (moderation, and the local upload
    # notification that stands in for the GCS -> Pub/Sub push).
    citizen_analyzer_url: str | None = None
    # Operator what-if plume runs per caller per hour.
    plume_what_if_per_hour: int = Field(default=30, ge=1)

    arangodb_url: str | None = None
    mlflow_tracking_uri: str | None = None
    drift_monitor_interval_seconds: int = Field(default=3600, ge=60)
    drift_monitor_reference_hours: int = Field(default=168, ge=1)
    drift_monitor_current_hours: int = Field(default=24, ge=1)
    drift_monitor_min_samples: int = Field(default=30, ge=10)
    drift_monitor_max_samples: int = Field(default=10000, ge=100)

    # Worker throughput guards. Detection is a whole-snapshot recompute, so
    # running it per message is pure waste once live volume arrives: one sweep
    # per batch yields the same answer for ~1/500th of the work.
    worker_detection_interval_seconds: float = Field(default=30.0, ge=0.0)
    worker_detection_max_batch: int = Field(default=500, ge=1)
    # The in-memory snapshot feeding detection is rebuilt from observations
    # held in process. Without a window it grows forever under a scheduler.
    worker_snapshot_hours: int = Field(default=48, ge=1)
    worker_metrics_port: int = Field(default=9090, ge=1, le=65535)

    @model_validator(mode="after")
    def _reject_weak_jwt_secret_outside_dev(self) -> "Settings":
        if self.environment.lower() in DEV_ENVIRONMENTS:
            return self
        secret = self.jwt_secret.get_secret_value()
        if secret == _DEV_JWT_SECRET or len(secret.encode()) < _MIN_JWT_SECRET_BYTES:
            raise ValueError(
                "AEROPULSE_JWT_SECRET must be set to a random value of at least "
                f"{_MIN_JWT_SECRET_BYTES} bytes when AEROPULSE_ENVIRONMENT="
                f"{self.environment!r}"
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()
