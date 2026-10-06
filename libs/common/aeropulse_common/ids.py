"""ULID helpers for observation, event, and correlation identifiers."""

from ulid import ULID


def new_ulid(prefix: str | None = None) -> str:
    """Generate a new ULID string, optionally prefixed.

    Args:
        prefix: Optional short prefix such as ``obs`` or ``evt``.

    Returns:
        A lexicographically sortable identifier.
    """
    value = str(ULID())
    if prefix:
        return f"{prefix}_{value}"
    return value
