"""One factory picks every storage adapter from ``AEROPULSE_PLATFORM`` (LLD APAC 3.5).

Credentials never appear here as values: MinIO keys come from ``SecretStr``
settings, Google Cloud uses Application Default Credentials.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from aeropulse_common.settings import Settings

from aeropulse_storage.analytics import (
    AnalyticsStore,
    BigQueryAnalyticsStore,
    ParquetAnalyticsStore,
)
from aeropulse_storage.archive import ObjectRawArchiver
from aeropulse_storage.artifacts import ObjectArtifactReader
from aeropulse_storage.citizen import CitizenReportStore
from aeropulse_storage.errors import StorageError
from aeropulse_storage.objects import (
    FilesystemObjectStore,
    GcsObjectStore,
    MinioObjectStore,
    ObjectStore,
)
from aeropulse_storage.plumes import REPLAY_PREFIX as PLUME_REPLAY_PREFIX
from aeropulse_storage.plumes import ObjectPlumeStore
from aeropulse_storage.snapshots import REPLAY_PREFIX, ObjectSnapshotStore

Concern = Literal["raw", "citizen", "models", "serving"]
CONCERNS: tuple[Concern, ...] = ("raw", "citizen", "models", "serving")


@dataclass(frozen=True)
class Storage:
    platform: Literal["local", "gcp"]
    objects: dict[Concern, ObjectStore]
    #: Bucket name per concern, as it appears in ``gs://`` / ``s3://`` URIs.
    buckets: dict[Concern, str]
    analytics: AnalyticsStore
    snapshots: ObjectSnapshotStore
    raw_archiver: ObjectRawArchiver
    max_query_bytes: int
    cache_dir: Path

    @property
    def replay_snapshots(self) -> ObjectSnapshotStore:
        return ObjectSnapshotStore(self.objects["serving"], prefix=REPLAY_PREFIX)

    @property
    def plumes(self) -> ObjectPlumeStore:
        return ObjectPlumeStore(self.objects["serving"])

    @property
    def replay_plumes(self) -> ObjectPlumeStore:
        return ObjectPlumeStore(self.objects["serving"], prefix=PLUME_REPLAY_PREFIX)

    @property
    def citizen(self) -> CitizenReportStore:
        return CitizenReportStore(self.objects["citizen"])

    def artifact_reader(self, fallback: object | None = None) -> ObjectArtifactReader:
        stores = {self.buckets[c]: self.objects[c] for c in CONCERNS}
        return ObjectArtifactReader(stores, self.cache_dir / "artifacts", fallback=fallback)


def build_storage(settings: Settings) -> Storage:
    if settings.platform == "gcp":
        return _gcp(settings)
    return _local(settings)


def _local(settings: Settings) -> Storage:
    root = settings.data_dir
    objects: dict[Concern, ObjectStore]
    buckets: dict[Concern, str]
    if settings.local_object_store == "minio":
        if settings.minio_access_key is None or settings.minio_secret_key is None:
            raise StorageError(
                "AEROPULSE_LOCAL_OBJECT_STORE=minio needs AEROPULSE_MINIO_ACCESS_KEY and "
                "AEROPULSE_MINIO_SECRET_KEY"
            )
        minio = importlib.import_module("minio")
        client = minio.Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key.get_secret_value(),
            secret_key=settings.minio_secret_key.get_secret_value(),
            secure=settings.minio_secure,
        )
        objects = {c: MinioObjectStore(client, settings.minio_bucket, prefix=c) for c in CONCERNS}
        buckets = {c: settings.minio_bucket for c in CONCERNS}
    else:
        objects = {c: FilesystemObjectStore(root / "objects" / c) for c in CONCERNS}
        buckets = {c: f"local-{c}" for c in CONCERNS}
    return Storage(
        platform="local",
        objects=objects,
        buckets=buckets,
        analytics=ParquetAnalyticsStore(root / "analytics"),
        snapshots=ObjectSnapshotStore(objects["serving"]),
        raw_archiver=ObjectRawArchiver(objects["raw"]),
        max_query_bytes=settings.bigquery_max_bytes,
        cache_dir=root / "cache",
    )


def _gcp(settings: Settings) -> Storage:
    if not settings.gcp_project:
        raise StorageError("AEROPULSE_PLATFORM=gcp needs AEROPULSE_GCP_PROJECT")
    prefix = settings.gcs_bucket or f"{settings.gcp_project}-aeropulse"
    buckets: dict[Concern, str] = {c: f"{prefix}-{c}" for c in CONCERNS}
    objects: dict[Concern, ObjectStore] = {c: GcsObjectStore(buckets[c]) for c in CONCERNS}
    return Storage(
        platform="gcp",
        objects=objects,
        buckets=buckets,
        analytics=BigQueryAnalyticsStore(settings.gcp_project, prefix=settings.bigquery_dataset),
        snapshots=ObjectSnapshotStore(objects["serving"]),
        raw_archiver=ObjectRawArchiver(objects["raw"]),
        max_query_bytes=settings.bigquery_max_bytes,
        cache_dir=settings.data_dir / "cache",
    )
