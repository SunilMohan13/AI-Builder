"""Full ``plume.v1`` objects (APAC LLD 8.5) on any ``ObjectStore``.

``plumes/{region_id}/{plume_id}.json`` in the serving bucket; the snapshot
carries only summaries and ids. Backfill plumes sit under ``backfill/`` and
fixture replays under their own prefix, as snapshots do, so neither can
replace a plume a live snapshot points at.
"""

from __future__ import annotations

from aeropulse_contracts.plume import Plume
from pydantic import ValidationError

from aeropulse_storage.errors import ObjectNotFoundError, StorageError
from aeropulse_storage.objects import ObjectStore, check_key
from aeropulse_storage.snapshots import SnapshotMode

PREFIX = "plumes"
REPLAY_PREFIX = "replay-plumes"


def plume_key(
    region_id: str, plume_id: str, *, mode: SnapshotMode = "live", prefix: str = PREFIX
) -> str:
    folder = f"{prefix}/{region_id}" if mode == "live" else f"{prefix}/{region_id}/backfill"
    return check_key(f"{folder}/{plume_id}.json")


class ObjectPlumeStore:
    def __init__(self, objects: ObjectStore, *, prefix: str = PREFIX) -> None:
        self.objects = objects
        self.prefix = prefix

    def write(self, plume: Plume, *, mode: SnapshotMode = "live") -> str:
        """Write (or overwrite: ids are deterministic) and return the URI."""
        key = plume_key(plume.region_id, plume.plume_id, mode=mode, prefix=self.prefix)
        body = plume.model_dump_json().encode()
        return self.objects.put(key, body, content_type="application/json").uri

    def get(self, region_id: str, plume_id: str, *, mode: SnapshotMode = "live") -> Plume | None:
        key = plume_key(region_id, plume_id, mode=mode, prefix=self.prefix)
        try:
            stored = self.objects.get(key)
        except ObjectNotFoundError:
            return None
        try:
            return Plume.model_validate_json(stored.data)
        except ValidationError as exc:
            raise StorageError(f"plume {key} does not match plume.v1: {exc}") from exc
