"""Object storage that fails closed.

A failed write raises. Callers must not receive a URI that points at nothing.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from aeropulse_observability.logging import get_logger

logger = get_logger("aeropulse.platform.objects")


class ObjectStoreError(Exception):
    """Raised when an object cannot be stored or read."""


@dataclass(frozen=True)
class StoredObject:
    """Bytes written under one key, plus the generation that wrote them."""

    key: str
    data: bytes
    content_type: str
    generation: int


class ObjectStore(Protocol):
    """Durable bytes addressed by key."""

    def put(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str,
        if_generation_match: int | None = None,
    ) -> StoredObject:
        """Store bytes. Raise on failure or a generation conflict."""
        ...

    def get(self, key: str) -> StoredObject:
        """Return the stored object. Raise if it is missing."""
        ...


class LocalObjectStore:
    """Filesystem store for local cycles and tests."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def put(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str,
        if_generation_match: int | None = None,
    ) -> StoredObject:
        """Write bytes atomically. A conflict or I/O error raises."""
        path = self._path(key)
        current = self._read_generation(key)
        if if_generation_match is not None and current != if_generation_match:
            raise ObjectStoreError(f"generation mismatch for {key}")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(path.name + ".tmp")
            temporary.write_bytes(data)
            os.replace(temporary, path)
            generation = current + 1
            path.with_name(path.name + ".generation").write_text(str(generation), encoding="utf-8")
            path.with_name(path.name + ".content_type").write_text(content_type, encoding="utf-8")
        except OSError as exc:
            logger.error("object_store.put_failed", key=key, error=type(exc).__name__)
            raise ObjectStoreError(f"put failed for {key}") from exc
        return StoredObject(key=key, data=data, content_type=content_type, generation=generation)

    def get(self, key: str) -> StoredObject:
        """Read a previously stored object."""
        path = self._path(key)
        if not path.is_file():
            raise ObjectStoreError(f"missing object {key}")
        content_type_path = path.with_name(path.name + ".content_type")
        content_type = (
            content_type_path.read_text(encoding="utf-8")
            if content_type_path.is_file()
            else "application/octet-stream"
        )
        return StoredObject(
            key=key,
            data=path.read_bytes(),
            content_type=content_type,
            generation=self._read_generation(key),
        )

    def _path(self, key: str) -> Path:
        if not key or key.startswith("/") or ".." in Path(key).parts:
            raise ObjectStoreError(f"invalid object key {key}")
        return self.root / key

    def _read_generation(self, key: str) -> int:
        path = self._path(key).with_name(self._path(key).name + ".generation")
        if not path.is_file():
            return 0
        try:
            return int(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise ObjectStoreError(f"corrupt generation for {key}") from exc
