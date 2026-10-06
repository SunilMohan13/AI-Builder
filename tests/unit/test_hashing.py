"""Tests for observation deduplication keys."""

from aeropulse_common.hashing import dedup_key


def test_dedup_key_is_stable() -> None:
    first = dedup_key("cpcb", "DL001_2026-09-08T05:15:00Z_pm25", "2026-09-08T05:15:00Z", "pm25")
    second = dedup_key("cpcb", "DL001_2026-09-08T05:15:00Z_pm25", "2026-09-08T05:15:00Z", "pm25")
    assert first == second
    assert len(first) == 64


def test_dedup_key_changes_with_parameter() -> None:
    a = dedup_key("cpcb", "DL001", "2026-09-08T05:15:00Z", "pm25")
    b = dedup_key("cpcb", "DL001", "2026-09-08T05:15:00Z", "pm10")
    assert a != b
