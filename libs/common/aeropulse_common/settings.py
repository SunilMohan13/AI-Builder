"""Environment-backed application settings.

Secrets are referenced by name only. Never log field values marked as secret.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_PUBLISHED_JWT_SECRET = "dev-only-change-me-use-32-bytes-min"


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

    jwt_secret: SecretStr
    jwt_algorithm: str = "HS256"
    jwt_issuer: str = "aeropulse"
    #: OIDC tokens are accepted only for these algorithms. The token header is ignored.
    oidc_algorithms: str = "RS256"
    # Extra CORS origins, comma-separated. Localhost plus Netlify and Render
    # subdomains are always allowed; this is for a custom domain.
    cors_origins: str = ""

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
    copilot_prompt_version: str = "v1"

    oidc_jwks_url: str | None = None
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

    @field_validator("jwt_secret")
    @classmethod
    def jwt_secret_fails_closed(cls, value: SecretStr) -> SecretStr:
        """Refuse a missing, short, or published secret."""
        raw = value.get_secret_value()
        if len(raw.encode("utf-8")) < 32:
            raise ValueError("jwt_secret must be at least 32 bytes")
        if raw == _PUBLISHED_JWT_SECRET:
            raise ValueError("jwt_secret refuses the published development default")
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()
