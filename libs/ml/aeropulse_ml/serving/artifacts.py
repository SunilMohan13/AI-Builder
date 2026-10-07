"""Turn a serving URI into a local file the resolver can hash and read."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable
from urllib.parse import urlparse

from aeropulse_common.errors import ModelServingError


@runtime_checkable
class ArtifactReader(Protocol):
    def local_path(self, uri: str) -> Path:
        """A readable local file for ``uri``; raises ``ModelServingError`` if not."""
        ...


class LocalArtifactReader:
    """Plain paths and ``file://`` URIs; relative paths resolve against ``base_dir``.

    Object-store URIs need the storage adapter, which supplies its own reader.
    """

    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir or Path.cwd()

    def local_path(self, uri: str) -> Path:
        parsed = urlparse(uri)
        if parsed.scheme == "file":
            path = Path(parsed.path)
        elif parsed.scheme in ("", "local"):
            path = Path(parsed.path if parsed.scheme else uri)
        else:
            raise ModelServingError(f"no reader configured for {parsed.scheme}:// URIs")
        if not path.is_absolute():
            path = self.base_dir / path
        if not path.is_file():
            raise ModelServingError(f"file not found: {uri}")
        return path
