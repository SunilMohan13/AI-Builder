"""Raw payload archive for the shared ingest pipeline."""

from __future__ import annotations

from aeropulse_storage.objects import ObjectStore


class ObjectRawArchiver:
    """``RawArchiver`` on an object store: returns the URI, raises on failure."""

    def __init__(self, objects: ObjectStore) -> None:
        self.objects = objects

    def __call__(self, key: str, body: bytes) -> str:
        return self.objects.put(key, body, content_type="application/json").uri
