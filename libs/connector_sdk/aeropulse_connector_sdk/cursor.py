"""Checkpoint cursor tokens for replay and live sources.

A replay cursor is a record offset into a static fixture. A live cursor has to
be a point in time, because the upstream keeps producing and there is no
stable ordinal to count. Both are stored in the same ``connector_checkpoint.cursor``
TEXT column, so the token is self-describing and a bare integer written by an
older build still parses.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict


class Cursor(BaseModel):
    """A source's resume position.

    Attributes:
        kind: ``offset`` for fixture replay, ``watermark`` for a live source.
        offset: Records already consumed, for ``offset`` cursors.
        watermark: Newest ``observed_at`` successfully published, for
            ``watermark`` cursors.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["offset", "watermark"] = "offset"
    offset: int | None = None
    watermark: datetime | None = None

    @classmethod
    def at_offset(cls, offset: int) -> Cursor:
        """Build an offset cursor, clamped to non-negative."""
        return cls(kind="offset", offset=max(0, offset))

    @classmethod
    def at_watermark(cls, watermark: datetime) -> Cursor:
        """Build a watermark cursor."""
        return cls(kind="watermark", watermark=watermark)

    def as_offset(self) -> int:
        """Return the record offset, or 0 when this is not an offset cursor."""
        if self.kind != "offset" or self.offset is None:
            return 0
        return max(0, self.offset)

    def window_start(self, overlap_seconds: int) -> datetime | None:
        """Return the fetch-window start for a live source.

        Args:
            overlap_seconds: How far to rewind before the watermark.

        Returns:
            The window start, or None when there is no watermark to resume
            from.

        Upstreams backfill late-arriving data, so resuming at exactly the
        watermark silently drops it. Re-requesting an overlap is cheap because
        the worker deduplicates on ``dedup_key`` (0001_init.sql:111-113,
        ``ON CONFLICT DO NOTHING``) — this overlap is only safe while that
        idempotency holds.
        """
        if self.watermark is None:
            return None
        return self.watermark - timedelta(seconds=max(0, overlap_seconds))


def parse_cursor(raw: str | None) -> Cursor:
    """Decode a stored cursor token.

    Accepts the bare integer format written before typed cursors existed, so
    an in-place upgrade resumes instead of restarting from zero.

    Args:
        raw: Stored token, or None when the source has no checkpoint.

    Returns:
        A ``Cursor``; an unparseable token degrades to offset zero rather than
        raising, because a corrupt checkpoint must not stop ingestion.
    """
    if raw in (None, ""):
        return Cursor.at_offset(0)
    text = str(raw).strip()
    if text.lstrip("-").isdigit():
        return Cursor.at_offset(int(text))
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        return Cursor.at_offset(0)
    if not isinstance(payload, dict):
        return Cursor.at_offset(0)
    try:
        return Cursor.model_validate(payload)
    except Exception:
        return Cursor.at_offset(0)


def encode_cursor(cursor: Cursor) -> str:
    """Encode a cursor for storage."""
    return cursor.model_dump_json(exclude_none=True)


def advance(
    previous: Cursor,
    *,
    live: bool,
    records_emitted: int,
    max_observed_at: datetime | None,
) -> Cursor:
    """Compute the next cursor after a successful run.

    Args:
        previous: Cursor the run started from.
        live: Whether the source resolved to live mode this cycle.
        records_emitted: Records published this run.
        max_observed_at: Newest observation timestamp published this run.

    Returns:
        The cursor to persist. A live run with no records keeps its previous
        watermark rather than resetting, so a quiet hour does not replay the
        whole window next cycle.
    """
    if live:
        if max_observed_at is None:
            return (
                previous if previous.kind == "watermark" else Cursor.at_watermark(datetime.now(UTC))
            )
        if previous.kind == "watermark" and previous.watermark is not None:
            return Cursor.at_watermark(max(previous.watermark, max_observed_at))
        return Cursor.at_watermark(max_observed_at)
    return Cursor.at_offset(previous.as_offset() + max(0, records_emitted))
