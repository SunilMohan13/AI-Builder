"""Serving snapshots (LLD APAC 6.3) on any ``ObjectStore``.

``snapshots/{region_id}/{cycle_time}.json`` is written first; the
``latest.json`` pointer moves only after that write succeeded, so the API
never reads a half-written snapshot. Re-running a cycle overwrites its own
object. Only a ``live`` snapshot newer than the current pointer moves it.

Backfill snapshots live under ``snapshots/{region_id}/backfill/``: the live
pointer names a live object, so a backfill of the same hour must not be able
to overwrite it.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Literal, Protocol, runtime_checkable

from aeropulse_contracts import RegionSnapshot
from pydantic import ValidationError

from aeropulse_storage.errors import ObjectNotFoundError, PreconditionFailedError, StorageError
from aeropulse_storage.objects import ObjectStore, check_key

PREFIX = "snapshots"
#: Fixture replays are kept apart so they can never overwrite a real snapshot.
REPLAY_PREFIX = "replay-snapshots"
LATEST = "latest.json"
#: Settings: pointer updates retried this many times on a concurrent write.
POINTER_RETRIES = 3

SnapshotMode = Literal["live", "backfill"]


@runtime_checkable
class SnapshotStore(Protocol):
    def write(self, snapshot: RegionSnapshot) -> str: ...

    def latest(self, region_id: str) -> RegionSnapshot | None: ...

    def get(
        self, region_id: str, cycle_time: datetime, *, mode: SnapshotMode = "live"
    ) -> RegionSnapshot | None: ...


def snapshot_key(
    region_id: str,
    cycle_time: datetime,
    *,
    mode: SnapshotMode = "live",
    prefix: str = PREFIX,
) -> str:
    stamp = cycle_time.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    folder = f"{prefix}/{region_id}" if mode == "live" else f"{prefix}/{region_id}/backfill"
    return check_key(f"{folder}/{stamp}.json")


class ObjectSnapshotStore:
    def __init__(self, objects: ObjectStore, *, prefix: str = PREFIX) -> None:
        self.objects = objects
        self.prefix = prefix

    def _pointer_key(self, region_id: str) -> str:
        return check_key(f"{self.prefix}/{region_id}/{LATEST}")

    def write(self, snapshot: RegionSnapshot) -> str:
        key = snapshot_key(
            snapshot.region_id, snapshot.cycle_time, mode=snapshot.mode, prefix=self.prefix
        )
        stored = self.objects.put(
            key, snapshot.model_dump_json().encode(), content_type="application/json"
        )
        if snapshot.mode == "live" and self.prefix == PREFIX:
            self._repoint(snapshot, key)
        return stored.uri

    def _repoint(self, snapshot: RegionSnapshot, key: str) -> None:
        pointer_key = self._pointer_key(snapshot.region_id)
        body = json.dumps(
            {"key": key, "cycle_time": snapshot.cycle_time.astimezone(UTC).isoformat()}
        ).encode()
        for _ in range(POINTER_RETRIES):
            try:
                current = self.objects.get(pointer_key)
            except ObjectNotFoundError:
                generation, current_time = 0, None
            else:
                generation = current.generation
                current_time = datetime.fromisoformat(json.loads(current.data)["cycle_time"])
            if current_time is not None and current_time > snapshot.cycle_time:
                return
            try:
                self.objects.put(
                    pointer_key,
                    body,
                    content_type="application/json",
                    if_generation_match=generation,
                )
            except PreconditionFailedError:
                continue
            return
        raise StorageError(f"latest pointer for {snapshot.region_id} kept changing; not moved")

    def latest(self, region_id: str) -> RegionSnapshot | None:
        try:
            pointer = self.objects.get(self._pointer_key(region_id))
        except ObjectNotFoundError:
            return None
        key = json.loads(pointer.data)["key"]
        return self._read(check_key(key))

    def get(
        self, region_id: str, cycle_time: datetime, *, mode: SnapshotMode = "live"
    ) -> RegionSnapshot | None:
        try:
            return self._read(snapshot_key(region_id, cycle_time, mode=mode, prefix=self.prefix))
        except ObjectNotFoundError:
            return None

    def _read(self, key: str) -> RegionSnapshot:
        stored = self.objects.get(key)
        try:
            return RegionSnapshot.model_validate_json(stored.data)
        except ValidationError as exc:
            raise StorageError(f"snapshot {key} does not match region_snapshot.v1: {exc}") from exc
