"""Object writes fail closed. A failed put does not invent a URI."""

from pathlib import Path

import pytest
from aeropulse_platform.object_store import LocalObjectStore, ObjectStoreError


def test_put_then_get_round_trip(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path)
    stored = store.put("snaps/latest.json", b"{}", content_type="application/json")
    assert stored.generation == 1
    assert store.get("snaps/latest.json").data == b"{}"


def test_generation_mismatch_raises(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path)
    store.put("a.json", b"1", content_type="application/json")
    with pytest.raises(ObjectStoreError):
        store.put("a.json", b"2", content_type="application/json", if_generation_match=0)


def test_put_raises_when_root_is_not_a_directory(tmp_path: Path) -> None:
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x", encoding="utf-8")
    store = LocalObjectStore(blocker)
    with pytest.raises(ObjectStoreError):
        store.put("a/b", b"data", content_type="application/json")
