"""Object storage (LLD APAC 3.5): filesystem, MinIO, Google Cloud Storage.

``put`` raises on failure, so no caller ever records a URI that points at
nothing. ``if_generation_match`` follows Cloud Storage: ``0`` means "only if
the object does not exist yet", ``N`` means "only if its generation is N".
"""

from __future__ import annotations

import fcntl
import importlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import timedelta
from io import BytesIO
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from aeropulse_storage.errors import ObjectNotFoundError, PreconditionFailedError, StorageError

_KEY = re.compile(r"^[A-Za-z0-9_.=\-]+(/[A-Za-z0-9_.=\-]+)*$")


def check_key(key: str) -> str:
    """Relative ``a/b/c`` keys only: no ``..``, no absolute paths, no odd characters."""
    if not _KEY.match(key) or any(part in ("", ".", "..") for part in key.split("/")):
        raise StorageError(f"invalid object key: {key!r}")
    return key


@dataclass(frozen=True)
class StoredObject:
    key: str
    data: bytes
    content_type: str
    generation: int
    uri: str


@runtime_checkable
class ObjectStore(Protocol):
    def put(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str,
        if_generation_match: int | None = None,
    ) -> StoredObject: ...

    def get(self, key: str) -> StoredObject: ...

    def exists(self, key: str) -> bool: ...

    def uri(self, key: str) -> str: ...

    def signed_upload_url(
        self, key: str, *, content_type: str, max_bytes: int, ttl_s: int
    ) -> str: ...

    def signed_download_url(self, key: str, *, ttl_s: int) -> str: ...


class FilesystemObjectStore:
    """Objects under ``root`` with a generation sidecar; for dev, tests and CI.

    Writes are atomic (temp file then rename) and the generation check runs
    under a per-object file lock, so two local writers cannot both win.
    """

    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, key: str) -> Path:
        return self.root / check_key(key)

    def _meta_path(self, key: str) -> Path:
        path = self._path(key)
        return path.with_name(f".{path.name}.meta.json")

    def _meta(self, key: str) -> dict[str, Any] | None:
        meta = self._meta_path(key)
        if not meta.is_file() or not self._path(key).is_file():
            return None
        return json.loads(meta.read_text(encoding="utf-8"))

    def uri(self, key: str) -> str:
        return self._path(key).resolve().as_uri()

    def exists(self, key: str) -> bool:
        return self._meta(key) is not None

    def put(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str,
        if_generation_match: int | None = None,
    ) -> StoredObject:
        path = self._path(key)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            lock_path = path.with_name(f".{path.name}.lock")
            with lock_path.open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                current = self._meta(key)
                generation = int(current["generation"]) if current else None
                if if_generation_match is not None and (generation or 0) != if_generation_match:
                    raise PreconditionFailedError(key, if_generation_match, generation)
                new_generation = (generation or 0) + 1
                _atomic_write(path, data)
                meta = {"generation": new_generation, "content_type": content_type}
                _atomic_write(self._meta_path(key), json.dumps(meta).encode())
        except OSError as exc:
            raise StorageError(f"could not write {key}: {exc}") from exc
        return StoredObject(key, data, content_type, new_generation, self.uri(key))

    def get(self, key: str) -> StoredObject:
        meta = self._meta(key)
        if meta is None:
            raise ObjectNotFoundError(key)
        try:
            data = self._path(key).read_bytes()
        except OSError as exc:
            raise StorageError(f"could not read {key}: {exc}") from exc
        return StoredObject(key, data, meta["content_type"], int(meta["generation"]), self.uri(key))

    def signed_upload_url(self, key: str, *, content_type: str, max_bytes: int, ttl_s: int) -> str:
        raise StorageError("signed URLs need MinIO or Cloud Storage; the filesystem store has none")

    def signed_download_url(self, key: str, *, ttl_s: int) -> str:
        raise StorageError("signed URLs need MinIO or Cloud Storage; the filesystem store has none")


def _atomic_write(path: Path, data: bytes) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp, path)
    except OSError:
        Path(tmp).unlink(missing_ok=True)
        raise


class MinioObjectStore:
    """MinIO (S3 API) for local Compose. Generation lives in object metadata.

    S3 has no compare-and-set on arbitrary generations, so the precondition is
    checked then written: safe with one writer per key, which the cycle's
    one-job-per-region rule guarantees. Cloud Storage enforces it server-side.
    """

    GENERATION_META = "x-amz-meta-aeropulse-generation"

    def __init__(self, client: Any, bucket: str, *, prefix: str = "") -> None:
        self.client = client
        self.bucket = bucket
        self.prefix = prefix.strip("/")

    def _name(self, key: str) -> str:
        check_key(key)
        return f"{self.prefix}/{key}" if self.prefix else key

    def uri(self, key: str) -> str:
        return f"s3://{self.bucket}/{self._name(key)}"

    def _generation(self, key: str) -> int | None:
        error = _minio_error()
        try:
            stat = self.client.stat_object(self.bucket, self._name(key))
        except error as exc:
            if getattr(exc, "code", "") in ("NoSuchKey", "NoSuchObject", "NoSuchBucket"):
                return None
            raise StorageError(f"could not stat {key}: {exc}") from exc
        metadata = {k.lower(): v for k, v in (stat.metadata or {}).items()}
        return int(metadata.get(self.GENERATION_META, 1))

    def exists(self, key: str) -> bool:
        return self._generation(key) is not None

    def put(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str,
        if_generation_match: int | None = None,
    ) -> StoredObject:
        current = self._generation(key)
        if if_generation_match is not None and (current or 0) != if_generation_match:
            raise PreconditionFailedError(key, if_generation_match, current)
        generation = (current or 0) + 1
        try:
            if not self.client.bucket_exists(self.bucket):
                self.client.make_bucket(self.bucket)
            self.client.put_object(
                self.bucket,
                self._name(key),
                BytesIO(data),
                length=len(data),
                content_type=content_type,
                metadata={"aeropulse-generation": str(generation)},
            )
        except _minio_error() as exc:
            raise StorageError(f"could not write {key}: {exc}") from exc
        return StoredObject(key, data, content_type, generation, self.uri(key))

    def get(self, key: str) -> StoredObject:
        generation = self._generation(key)
        if generation is None:
            raise ObjectNotFoundError(key)
        try:
            response = self.client.get_object(self.bucket, self._name(key))
            try:
                data = response.read()
                content_type = response.headers.get("Content-Type", "application/octet-stream")
            finally:
                response.close()
                response.release_conn()
        except _minio_error() as exc:
            raise StorageError(f"could not read {key}: {exc}") from exc
        return StoredObject(key, data, content_type, generation, self.uri(key))

    def signed_upload_url(self, key: str, *, content_type: str, max_bytes: int, ttl_s: int) -> str:
        # A presigned S3 PUT cannot cap the body size; the analyzer re-checks it.
        return self.client.presigned_put_object(
            self.bucket, self._name(key), expires=timedelta(seconds=ttl_s)
        )

    def signed_download_url(self, key: str, *, ttl_s: int) -> str:
        return self.client.presigned_get_object(
            self.bucket, self._name(key), expires=timedelta(seconds=ttl_s)
        )


def _minio_error() -> type[Exception]:
    return importlib.import_module("minio.error").S3Error


class GcsObjectStore:
    """Cloud Storage; preconditions are enforced by the service."""

    def __init__(self, bucket: str, *, client: Any | None = None) -> None:
        self.bucket_name = bucket
        self._client = client

    def _bucket(self) -> Any:
        if self._client is None:
            try:
                storage = importlib.import_module("google.cloud.storage")
            except ImportError as exc:
                raise StorageError(
                    "google-cloud-storage is not installed; install aeropulse-storage[gcp]"
                ) from exc
            self._client = storage.Client()
        return self._client.bucket(self.bucket_name)

    def uri(self, key: str) -> str:
        return f"gs://{self.bucket_name}/{check_key(key)}"

    def exists(self, key: str) -> bool:
        return bool(self._bucket().blob(check_key(key)).exists())

    def put(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str,
        if_generation_match: int | None = None,
    ) -> StoredObject:
        blob = self._bucket().blob(check_key(key))
        exceptions = _gcs_exceptions()
        try:
            blob.upload_from_string(
                data, content_type=content_type, if_generation_match=if_generation_match
            )
        except exceptions.PreconditionFailed as exc:
            raise PreconditionFailedError(key, if_generation_match or 0, None) from exc
        except exceptions.GoogleAPICallError as exc:
            raise StorageError(f"could not write {key}: {exc}") from exc
        return StoredObject(key, data, content_type, int(blob.generation or 0), self.uri(key))

    def get(self, key: str) -> StoredObject:
        blob = self._bucket().blob(check_key(key))
        exceptions = _gcs_exceptions()
        try:
            data = blob.download_as_bytes()
        except exceptions.NotFound as exc:
            raise ObjectNotFoundError(key) from exc
        except exceptions.GoogleAPICallError as exc:
            raise StorageError(f"could not read {key}: {exc}") from exc
        content_type = blob.content_type or "application/octet-stream"
        return StoredObject(key, data, content_type, int(blob.generation or 0), self.uri(key))

    def _signer(self) -> dict[str, str]:
        """How to sign: locally with a key, else IAM ``signBlob`` as the runtime identity.

        Cloud Run credentials carry a token but no private key, so passing the
        identity's email and token makes the client call ``signBlob`` instead.
        """
        self._bucket()
        credentials = getattr(self._client, "_credentials", None)
        signing = importlib.import_module("google.auth.credentials").Signing
        if credentials is None or isinstance(credentials, signing):
            return {}
        if not credentials.valid:
            transport = importlib.import_module("google.auth.transport.requests")
            credentials.refresh(transport.Request())
        return {
            "service_account_email": credentials.service_account_email,
            "access_token": credentials.token,
        }

    def signed_upload_url(self, key: str, *, content_type: str, max_bytes: int, ttl_s: int) -> str:
        blob = self._bucket().blob(check_key(key))
        return blob.generate_signed_url(
            version="v4",
            expiration=timedelta(seconds=ttl_s),
            method="PUT",
            content_type=content_type,
            headers={"x-goog-content-length-range": f"0,{max_bytes}"},
            **self._signer(),
        )

    def signed_download_url(self, key: str, *, ttl_s: int) -> str:
        blob = self._bucket().blob(check_key(key))
        return blob.generate_signed_url(
            version="v4", expiration=timedelta(seconds=ttl_s), method="GET", **self._signer()
        )


def _gcs_exceptions() -> Any:
    return importlib.import_module("google.api_core.exceptions")
