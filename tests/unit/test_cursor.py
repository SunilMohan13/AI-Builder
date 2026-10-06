"""Checkpoint cursor semantics for replay offsets and live watermarks."""

from datetime import UTC, datetime, timedelta

from aeropulse_connector_sdk.checkpoint import apply_cursor
from aeropulse_connector_sdk.cursor import Cursor, advance, encode_cursor, parse_cursor

T0 = datetime(2026, 9, 8, 6, 0, tzinfo=UTC)


def test_bare_integer_from_an_older_build_still_parses() -> None:
    """Existing rows are plain integers; an upgrade must resume, not restart."""
    cursor = parse_cursor("12")
    assert cursor.kind == "offset"
    assert cursor.as_offset() == 12


def test_empty_and_none_mean_start_from_the_beginning() -> None:
    assert parse_cursor(None).as_offset() == 0
    assert parse_cursor("").as_offset() == 0


def test_corrupt_token_degrades_to_zero_rather_than_raising() -> None:
    """A bad checkpoint must not stop ingestion."""
    assert parse_cursor("not-a-cursor").as_offset() == 0
    assert parse_cursor("{broken").as_offset() == 0
    assert parse_cursor("[1,2,3]").as_offset() == 0


def test_offset_round_trip() -> None:
    encoded = encode_cursor(Cursor.at_offset(7))
    assert parse_cursor(encoded).as_offset() == 7


def test_watermark_round_trip() -> None:
    encoded = encode_cursor(Cursor.at_watermark(T0))
    restored = parse_cursor(encoded)
    assert restored.kind == "watermark"
    assert restored.watermark == T0


def test_negative_offsets_clamp_to_zero() -> None:
    assert Cursor.at_offset(-5).as_offset() == 0
    assert parse_cursor("-5").as_offset() == 0


def test_replay_advance_counts_records() -> None:
    nxt = advance(Cursor.at_offset(10), live=False, records_emitted=5, max_observed_at=None)
    assert nxt.kind == "offset"
    assert nxt.as_offset() == 15


def test_live_advance_takes_the_newest_observation() -> None:
    nxt = advance(Cursor.at_offset(0), live=True, records_emitted=3, max_observed_at=T0)
    assert nxt.kind == "watermark"
    assert nxt.watermark == T0


def test_live_watermark_never_moves_backwards() -> None:
    """A late batch of older rows must not rewind the resume point."""
    previous = Cursor.at_watermark(T0)
    older = T0 - timedelta(hours=3)
    nxt = advance(previous, live=True, records_emitted=2, max_observed_at=older)
    assert nxt.watermark == T0


def test_live_run_with_no_records_keeps_its_watermark() -> None:
    """A quiet hour must not replay the whole window next cycle."""
    previous = Cursor.at_watermark(T0)
    nxt = advance(previous, live=True, records_emitted=0, max_observed_at=None)
    assert nxt.watermark == T0


def test_window_start_rewinds_by_the_overlap() -> None:
    cursor = Cursor.at_watermark(T0)
    assert cursor.window_start(3600) == T0 - timedelta(hours=1)


def test_window_start_is_none_without_a_watermark() -> None:
    assert Cursor.at_offset(4).window_start(3600) is None


def test_apply_cursor_still_slices_on_an_offset() -> None:
    assert apply_cursor([1, 2, 3, 4], "2") == [3, 4]
    assert apply_cursor([1, 2, 3, 4], None) == [1, 2, 3, 4]


def test_apply_cursor_treats_a_watermark_as_start_from_the_beginning() -> None:
    """A live connector windows by time; it never slices a fixture by offset."""
    token = encode_cursor(Cursor.at_watermark(T0))
    assert apply_cursor([1, 2, 3, 4], token) == [1, 2, 3, 4]
