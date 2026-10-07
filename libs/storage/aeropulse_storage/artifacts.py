"""Model artifacts from object storage, for the serving resolver.

Downloads land in a local cache; the resolver still checks the gate report's
SHA-256 before unpickling, so a tampered cache file is refused, not served.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from aeropulse_common.errors import ModelServingError

from aeropulse_storage.errors import StorageError
from aeropulse_storage.objects import ObjectStore


class ObjectArtifactReader:
    """``gs://`` / ``s3://`` URIs via the store that owns the bucket; others via ``fallback``."""

    def __init__(
        self,
        stores: Mapping[str, ObjectStore],
        cache_dir: Path,
        *,
        fallback: Any | None = None,
    ) -> None:
        self.stores = dict(stores)
        self.cache_dir = cache_dir
        self.fallback = fallback

    def local_path(self, uri: str) -> Path:
        parsed = urlparse(uri)
        if parsed.scheme not in ("gs", "s3"):
            if self.fallback is None:
                raise ModelServingError(f"no reader configured for {parsed.scheme or 'path'} URIs")
            return self.fallback.local_path(uri)
        store = self.stores.get(parsed.netloc)
        if store is None:
            raise ModelServingError(f"no object store configured for bucket {parsed.netloc}")
        key = parsed.path.lstrip("/")
        # Fetched afresh on every resolve: the resolver loads once per process,
        # and a stale cache would otherwise be refused on hash until cleared.
        target = self.cache_dir / hashlib.sha256(uri.encode()).hexdigest() / Path(key).name
        try:
            data = store.get(key).data
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        except (StorageError, OSError) as exc:
            raise ModelServingError(f"could not fetch {uri}: {exc}") from exc
        return target
