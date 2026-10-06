"""Idempotency and deduplication helpers."""

from hashlib import sha256


def dedup_key(
    source_id: str,
    source_record_id: str,
    observed_at: str,
    parameter: str,
) -> str:
    """Build the canonical observation deduplication key.

    Args:
        source_id: Registered source identifier (e.g. ``cpcb``).
        source_record_id: Provider-native record id.
        observed_at: ISO-8601 timestamp of the observation.
        parameter: Measured parameter name (e.g. ``pm25``).

    Returns:
        Hex SHA-256 digest of the joined identity tuple.
    """
    material = "|".join((source_id, source_record_id, observed_at, parameter))
    return sha256(material.encode("utf-8")).hexdigest()
