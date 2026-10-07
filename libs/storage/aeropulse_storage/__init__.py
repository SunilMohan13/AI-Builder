"""Storage adapters behind one factory (LLD APAC 3.5).

Cloud SDKs are imported lazily, only inside the GCS, MinIO and BigQuery
adapter classes; the rest of the code sees ``ObjectStore``,
``AnalyticsStore`` and ``SnapshotStore``.
"""

from aeropulse_storage.analytics import (
    DEFAULT_MAX_BYTES,
    TABLES,
    TEMPLATES,
    AnalyticsStore,
    BigQueryAnalyticsStore,
    ParquetAnalyticsStore,
    QueryTemplate,
    batch_id,
)
from aeropulse_storage.archive import ObjectRawArchiver
from aeropulse_storage.artifacts import ObjectArtifactReader
from aeropulse_storage.citizen import (
    CitizenReportStore,
    citizen_row,
    report_id_from_incoming,
    report_key,
)
from aeropulse_storage.errors import ObjectNotFoundError, PreconditionFailedError, StorageError
from aeropulse_storage.factory import CONCERNS, Storage, build_storage
from aeropulse_storage.objects import (
    FilesystemObjectStore,
    GcsObjectStore,
    MinioObjectStore,
    ObjectStore,
    StoredObject,
)
from aeropulse_storage.plumes import ObjectPlumeStore, plume_key
from aeropulse_storage.snapshots import ObjectSnapshotStore, SnapshotStore, snapshot_key

__all__ = [
    "CONCERNS",
    "DEFAULT_MAX_BYTES",
    "TABLES",
    "TEMPLATES",
    "AnalyticsStore",
    "BigQueryAnalyticsStore",
    "CitizenReportStore",
    "FilesystemObjectStore",
    "GcsObjectStore",
    "MinioObjectStore",
    "ObjectArtifactReader",
    "ObjectNotFoundError",
    "ObjectPlumeStore",
    "ObjectRawArchiver",
    "ObjectSnapshotStore",
    "ObjectStore",
    "ParquetAnalyticsStore",
    "PreconditionFailedError",
    "QueryTemplate",
    "SnapshotStore",
    "Storage",
    "StorageError",
    "StoredObject",
    "batch_id",
    "build_storage",
    "citizen_row",
    "plume_key",
    "report_id_from_incoming",
    "report_key",
    "snapshot_key",
]
