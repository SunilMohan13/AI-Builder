"""MinIO/S3 helpers for immutable raw payloads (LLD section 11)."""

from __future__ import annotations

from datetime import UTC, datetime

import structlog

from aeropulse_common.settings import Settings, get_settings

logger = structlog.get_logger("aeropulse.common.objects")


def raw_object_uri(source_id: str, name: str, *, now: datetime | None = None) -> str:
    """Return the canonical raw-object key (even if MinIO is down)."""
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    return f"s3://aeropulse/raw/{source_id}/{stamp}/{name}"


def put_raw_json(
    source_id: str,
    name: str,
    payload: bytes,
    settings: Settings | None = None,
    content_type: str = "application/json",
) -> str:
    """Upload raw bytes to MinIO. Soft-fails to a logical URI if the store is down.

    Note: on failure the returned ``s3://`` URI is logical only — nothing was
    written, so `provenance.raw_object_uri` will not resolve. Callers must not
    assume the returned URI is fetchable; check the logs for
    ``objects.raw_copy_not_stored`` to know when that happened.

    Args:
        source_id: Connector source.
        name: Object basename.
        payload: Object bytes (JSON, image, or other).
        settings: Optional settings override.
        content_type: Stored object type. JSON by default; photos pass image/*.

    Returns:
        ``s3://`` URI.
    """
    cfg = settings or get_settings()
    uri = raw_object_uri(source_id, name)
    if cfg.minio_access_key is None or cfg.minio_secret_key is None:
        logger.warning(
            "objects.raw_copy_not_stored",
            reason="no_credentials",
            source_id=source_id,
            uri=uri,
        )
        return uri
    try:
        from minio import Minio

        client = Minio(
            cfg.minio_endpoint,
            access_key=cfg.minio_access_key.get_secret_value(),
            secret_key=cfg.minio_secret_key.get_secret_value(),
            secure=cfg.minio_secure,
        )
        if not client.bucket_exists(cfg.minio_bucket):
            client.make_bucket(cfg.minio_bucket)
        from io import BytesIO

        key = uri.removeprefix("s3://aeropulse/")
        client.put_object(
            cfg.minio_bucket,
            key,
            BytesIO(payload),
            length=len(payload),
            content_type=content_type,
        )
    except Exception as exc:
        logger.warning(
            "objects.raw_copy_not_stored",
            reason="minio_error",
            source_id=source_id,
            uri=uri,
            error=str(exc),
        )
        return uri
    return uri
