"""Cursor helpers for incremental replay fetches.

The project defines ``FetchRequest.cursor`` but had no connector semantics for it.
This module adds the smallest real behavior: the cursor is treated as a
zero-based record offset for replay-mode fetches. That makes incremental pulls
possible without inventing a separate storage layer or a provider-specific API.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypeVar

from aeropulse_connector_sdk.cursor import parse_cursor

T = TypeVar("T")


def apply_cursor(items: Sequence[T], cursor: str | None) -> list[T]:
    """Return the subsequence starting after the cursor offset.

    Args:
        items: Sequence to slice.
        cursor: Optional zero-based index. ``None`` or empty means start at the
            beginning. Negative values are clamped to zero. A live source's
            watermark token carries no offset, so it reads as "start at the
            beginning" rather than raising — a live connector windows its own
            fetch by time and never slices a fixture.

    Returns:
        A new list representing the remaining records after the cursor.
    """
    if cursor is None or cursor == "":
        return list(items)
    start = parse_cursor(cursor).as_offset()
    return list(items)[start:]
