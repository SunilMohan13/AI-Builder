"""Storage adapters (LLD APAC 3.5): object, analytics, snapshot, factory."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from aeropulse_common.errors import ModelServingError
from aeropulse_common.settings import Settings
from aeropulse_contracts import RegionSnapshot
from aeropulse_storage import (
    TEMPLATES,
    BigQueryAnalyticsStore,
    FilesystemObjectStore,
    GcsObjectStore,
    MinioObjectStore,
    ObjectArtifactReader,
    ObjectNotFoundError,
    ObjectRawArchiver,
    ObjectSnapshotStore,
    ParquetAnalyticsStore,
    PreconditionFailedError,
    StorageError,
    batch_id,
    build_storage,
    snapshot_key,
)
from aeropulse_storage.snapshots import REPLAY_PREFIX

T0 = datetime(2026, 9, 8, 6, tzinfo=UTC)


def _snapshot(t: datetime, mode: str = "live", region: str = "in-north") -> RegionSnapshot:
    return RegionSnapshot(
        region_id=region,
        cycle_time=t,
        cycle_id=f"{region}_{t:%Y%m%dT%H%MZ}_{mode}",
        pack_version="1",
        mode=mode,  # type: ignore[arg-type]
        generated_at=t + timedelta(minutes=5),
    )


# --- filesystem object store -------------------------------------------------


def test_filesystem_put_get_round_trip_with_generations(tmp_path: Path) -> None:
    store = FilesystemObjectStore(tmp_path)
    first = store.put("a/b.json", b"{}", content_type="application/json")
    second = store.put("a/b.json", b"[1]", content_type="application/json")
    assert (first.generation, second.generation) == (1, 2)
    got = store.get("a/b.json")
    assert got.data == b"[1]" and got.generation == 2 and got.content_type == "application/json"
    assert got.uri.startswith("file://") and store.exists("a/b.json")


def test_filesystem_generation_preconditions(tmp_path: Path) -> None:
    store = FilesystemObjectStore(tmp_path)
    store.put("k", b"1", content_type="text/plain", if_generation_match=0)
    with pytest.raises(PreconditionFailedError):
        store.put("k", b"2", content_type="text/plain", if_generation_match=0)
    with pytest.raises(PreconditionFailedError):
        store.put("k", b"2", content_type="text/plain", if_generation_match=7)
    assert store.put("k", b"2", content_type="text/plain", if_generation_match=1).generation == 2
    assert store.get("k").data == b"2"


def test_filesystem_missing_object_and_bad_keys(tmp_path: Path) -> None:
    store = FilesystemObjectStore(tmp_path)
    with pytest.raises(ObjectNotFoundError):
        store.get("nope")
    assert not store.exists("nope")
    for key in ("../escape", "/abs", "a//b", "a/./b", "sp ace", ""):
        with pytest.raises(StorageError):
            store.put(key, b"x", content_type="text/plain")


def test_filesystem_has_no_signed_urls(tmp_path: Path) -> None:
    store = FilesystemObjectStore(tmp_path)
    with pytest.raises(StorageError, match="signed URLs"):
        store.signed_upload_url("k", content_type="image/jpeg", max_bytes=10, ttl_s=60)
    with pytest.raises(StorageError, match="signed URLs"):
        store.signed_download_url("k", ttl_s=60)


def test_raw_archiver_returns_uri_and_raises_on_failure(tmp_path: Path) -> None:
    archiver = ObjectRawArchiver(FilesystemObjectStore(tmp_path))
    uri = archiver("raw/in-north/openaq/2026/09/08/run.json", b"[]")
    assert uri.endswith("raw/in-north/openaq/2026/09/08/run.json")
    with pytest.raises(StorageError):
        archiver("../bad", b"[]")


# --- MinIO / GCS with fake clients -------------------------------------------


class _S3Error(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _FakeMinio:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str, dict[str, str]]] = {}
        self.buckets: set[str] = set()

    def bucket_exists(self, bucket: str) -> bool:
        return bucket in self.buckets

    def make_bucket(self, bucket: str) -> None:
        self.buckets.add(bucket)

    def stat_object(self, bucket: str, name: str) -> Any:
        if name not in self.objects:
            raise _S3Error("NoSuchKey")
        meta = {f"X-Amz-Meta-{k.title()}": v for k, v in self.objects[name][2].items()}
        return type("Stat", (), {"metadata": meta})()

    def put_object(self, bucket, name, data: BytesIO, *, length, content_type, metadata):
        self.objects[name] = (data.read(length), content_type, metadata)

    def get_object(self, bucket: str, name: str) -> Any:
        body, content_type, _ = self.objects[name]

        class _Response:
            def __init__(self) -> None:
                self.headers = {"Content-Type": content_type}

            def read(self) -> bytes:
                return body

            def close(self) -> None: ...

            def release_conn(self) -> None: ...

        return _Response()

    def presigned_put_object(self, bucket: str, name: str, *, expires: timedelta) -> str:
        return f"https://minio.local/{bucket}/{name}?put&ttl={int(expires.total_seconds())}"

    def presigned_get_object(self, bucket: str, name: str, *, expires: timedelta) -> str:
        return f"https://minio.local/{bucket}/{name}?get"


@pytest.fixture
def fake_minio(monkeypatch: pytest.MonkeyPatch) -> _FakeMinio:
    import aeropulse_storage.objects as objects

    monkeypatch.setattr(objects, "_minio_error", lambda: _S3Error)
    return _FakeMinio()


def test_minio_store_generations_and_preconditions(fake_minio: _FakeMinio) -> None:
    store = MinioObjectStore(fake_minio, "aeropulse", prefix="serving")
    assert not store.exists("x.json")
    assert store.put("x.json", b"1", content_type="application/json").generation == 1
    assert "serving/x.json" in fake_minio.objects and "aeropulse" in fake_minio.buckets
    with pytest.raises(PreconditionFailedError):
        store.put("x.json", b"2", content_type="application/json", if_generation_match=0)
    stored = store.put("x.json", b"2", content_type="application/json", if_generation_match=1)
    assert stored.generation == 2 and stored.uri == "s3://aeropulse/serving/x.json"
    assert store.get("x.json").data == b"2"
    with pytest.raises(ObjectNotFoundError):
        store.get("missing.json")
    url = store.signed_upload_url("x.json", content_type="image/jpeg", max_bytes=5, ttl_s=300)
    assert "ttl=300" in url


class _GoogleAPICallError(Exception): ...


class _PreconditionFailedError(_GoogleAPICallError): ...


class _NotFoundError(_GoogleAPICallError): ...


class _GcsExceptions:
    """Stands in for ``google.api_core.exceptions``; the SDK is an optional extra."""

    GoogleAPICallError = _GoogleAPICallError
    PreconditionFailed = _PreconditionFailedError
    NotFound = _NotFoundError


class _FakeBlob:
    def __init__(self, bucket: _FakeBucket, name: str) -> None:
        self.bucket, self.name = bucket, name
        self.generation: int | None = None
        self.content_type: str | None = None

    def exists(self) -> bool:
        return self.name in self.bucket.data

    def upload_from_string(self, data: bytes, *, content_type: str, if_generation_match):
        current = self.bucket.data.get(self.name)
        generation = current[2] if current else 0
        if if_generation_match is not None and if_generation_match != generation:
            raise _PreconditionFailedError("generation mismatch")
        self.generation = generation + 1
        self.bucket.data[self.name] = (data, content_type, self.generation)

    def download_as_bytes(self) -> bytes:
        if self.name not in self.bucket.data:
            raise _NotFoundError("no such object")
        data, self.content_type, self.generation = self.bucket.data[self.name]
        return data

    def generate_signed_url(self, **kwargs: Any) -> str:
        self.bucket.signed.append(kwargs)
        return f"https://storage.googleapis.com/{self.name}?sig"


class _FakeBucket:
    def __init__(self) -> None:
        self.data: dict[str, tuple[bytes, str, int]] = {}
        self.signed: list[dict[str, Any]] = []

    def blob(self, name: str) -> _FakeBlob:
        return _FakeBlob(self, name)


class _FakeGcs:
    def __init__(self) -> None:
        self.buckets: dict[str, _FakeBucket] = {}

    def bucket(self, name: str) -> _FakeBucket:
        return self.buckets.setdefault(name, _FakeBucket())


def test_gcs_store_maps_preconditions_and_signs_with_a_size_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import aeropulse_storage.objects as objects

    monkeypatch.setattr(objects, "_gcs_exceptions", lambda: _GcsExceptions)
    client = _FakeGcs()
    store = GcsObjectStore("p-aeropulse-serving", client=client)
    assert store.put("a.json", b"1", content_type="application/json").generation == 1
    with pytest.raises(PreconditionFailedError):
        store.put("a.json", b"2", content_type="application/json", if_generation_match=0)
    assert store.get("a.json").data == b"1"
    with pytest.raises(ObjectNotFoundError):
        store.get("b.json")
    assert store.uri("a.json") == "gs://p-aeropulse-serving/a.json"
    store.signed_upload_url("up.jpg", content_type="image/jpeg", max_bytes=5_000_000, ttl_s=600)
    signed = client.buckets["p-aeropulse-serving"].signed[-1]
    assert signed["method"] == "PUT" and signed["version"] == "v4"
    assert signed["headers"] == {"x-goog-content-length-range": "0,5000000"}


# --- analytics -------------------------------------------------------------


def _raw_rows(n: int, start: datetime = T0, region: str = "in-north") -> list[dict[str, Any]]:
    return [
        {
            "region_id": region,
            "known_at": start - timedelta(hours=i),
            "record": json.dumps({"i": i}),
        }
        for i in range(n)
    ]


def test_batch_id_is_content_derived() -> None:
    rows = _raw_rows(3)
    assert batch_id("c1", rows) == batch_id("c1", list(reversed(rows)))
    assert batch_id("c1", rows) != batch_id("c1", rows[:2])
    assert batch_id("in-north 06:00", rows).startswith("in-north_06_00_")


def test_parquet_load_is_idempotent_per_batch(tmp_path: Path) -> None:
    store = ParquetAnalyticsStore(tmp_path)
    rows = _raw_rows(3)
    assert store.load("raw.air_quality", rows, batch_id="b1") == 3
    assert store.load("raw.air_quality", rows, batch_id="b1") == 3
    assert len(store.read("raw.air_quality")) == 3
    assert store.load("raw.air_quality", [], batch_id="b1") == 0
    assert len(store.read("raw.air_quality")) == 3, "an empty load must not erase a batch"


def test_parquet_rejects_unknown_tables_and_bad_batch_ids(tmp_path: Path) -> None:
    store = ParquetAnalyticsStore(tmp_path)
    with pytest.raises(StorageError, match="unknown analytics table"):
        store.load("raw.secrets", _raw_rows(1), batch_id="b")
    with pytest.raises(StorageError, match="invalid batch id"):
        store.load("raw.air_quality", _raw_rows(1), batch_id="../b")


def test_query_takes_templates_only(tmp_path: Path) -> None:
    store = ParquetAnalyticsStore(tmp_path)
    with pytest.raises(StorageError, match="unknown query template"):
        store.query("SELECT * FROM raw", {})
    with pytest.raises(StorageError, match="missing"):
        store.query("raw.air_quality.window", {"region_id": "in-north"})
    with pytest.raises(StorageError, match="unexpected"):
        store.query(
            "raw.air_quality.window",
            {"region_id": "in-north", "start": T0, "end": T0, "sql": "DROP"},
        )


def test_raw_window_filters_region_and_half_open_time(tmp_path: Path) -> None:
    store = ParquetAnalyticsStore(tmp_path)
    store.load("raw.air_quality", _raw_rows(5), batch_id="a")
    store.load("raw.air_quality", _raw_rows(2, region="sg-singapore"), batch_id="b")
    rows = store.query(
        "raw.air_quality.window",
        {"region_id": "in-north", "start": T0 - timedelta(hours=2), "end": T0},
    )
    assert sorted(json.loads(r["record"])["i"] for r in rows) == [1, 2]
    empty = store.query("raw.weather.window", {"region_id": "in-north", "start": T0, "end": T0})
    assert empty == []


def test_watermark_template_takes_the_newest_per_source(tmp_path: Path) -> None:
    store = ParquetAnalyticsStore(tmp_path)
    rows = [
        {"region_id": "in-north", "source_id": "openaq", "watermark": T0 - timedelta(hours=2)},
        {"region_id": "in-north", "source_id": "openaq", "watermark": T0},
        {"region_id": "in-north", "source_id": "firms", "watermark": None},
        {"region_id": "au-nsw", "source_id": "openaq", "watermark": T0 + timedelta(hours=9)},
    ]
    store.load("ops.source_health", rows, batch_id="h")
    got = store.query("ops.source_health.watermarks", {"region_id": "in-north"})
    assert got == [{"source_id": "openaq", "watermark": T0}]


def test_every_template_names_a_known_table_and_parameterised_sql() -> None:
    for template in TEMPLATES.values():
        assert "{table}" in template.sql
        for name in template.params:
            assert f"@{name}" in template.sql


def test_bigquery_store_validates_identifiers_and_needs_the_sdk() -> None:
    with pytest.raises(StorageError, match="project"):
        BigQueryAnalyticsStore("Bad Project")
    with pytest.raises(StorageError, match="prefix"):
        BigQueryAnalyticsStore("my-project-1", prefix="a-b")
    store = BigQueryAnalyticsStore("my-project-1")
    assert store.table_id("raw.air_quality") == "my-project-1.aeropulse_raw.air_quality"
    with pytest.raises(StorageError, match="unknown analytics table"):
        store.table_id("raw.nope")


# --- snapshots -------------------------------------------------------------


def test_snapshot_write_then_latest(tmp_path: Path) -> None:
    store = ObjectSnapshotStore(FilesystemObjectStore(tmp_path))
    assert store.latest("in-north") is None
    uri = store.write(_snapshot(T0))
    assert uri.endswith(snapshot_key("in-north", T0))
    latest = store.latest("in-north")
    assert latest is not None and latest.cycle_time == T0
    assert store.get("in-north", T0) == latest
    assert store.get("in-north", T0 + timedelta(hours=1)) is None


def test_rewriting_a_cycle_is_idempotent(tmp_path: Path) -> None:
    objects = FilesystemObjectStore(tmp_path)
    store = ObjectSnapshotStore(objects)
    store.write(_snapshot(T0))
    store.write(_snapshot(T0))
    files = [
        p
        for p in (tmp_path / "snapshots" / "in-north").iterdir()
        if p.suffix == ".json" and not p.name.startswith(".")
    ]
    assert sorted(p.name for p in files) == ["20260908T060000Z.json", "latest.json"]
    assert store.latest("in-north") is not None


def test_pointer_only_moves_forward_and_only_for_live(tmp_path: Path) -> None:
    store = ObjectSnapshotStore(FilesystemObjectStore(tmp_path))
    store.write(_snapshot(T0))
    store.write(_snapshot(T0 - timedelta(hours=1)))
    store.write(_snapshot(T0 + timedelta(hours=1), mode="backfill"))
    latest = store.latest("in-north")
    assert latest is not None and latest.cycle_time == T0 and latest.mode == "live"
    assert store.get("in-north", T0 + timedelta(hours=1)) is None
    assert store.get("in-north", T0 + timedelta(hours=1), mode="backfill") is not None
    store.write(_snapshot(T0 + timedelta(hours=2)))
    latest = store.latest("in-north")
    assert latest is not None and latest.cycle_time == T0 + timedelta(hours=2)


def test_a_backfill_of_the_same_hour_cannot_overwrite_the_live_snapshot(tmp_path: Path) -> None:
    store = ObjectSnapshotStore(FilesystemObjectStore(tmp_path))
    store.write(_snapshot(T0))
    store.write(_snapshot(T0, mode="backfill"))
    latest = store.latest("in-north")
    assert latest is not None and latest.mode == "live"
    live, backfill = store.get("in-north", T0), store.get("in-north", T0, mode="backfill")
    assert live is not None and live.mode == "live"
    assert backfill is not None and backfill.mode == "backfill"


class _FailingStore(FilesystemObjectStore):
    def put(self, key: str, data: bytes, **kwargs: Any):
        if "latest" not in key:
            raise StorageError("disk full")
        return super().put(key, data, **kwargs)


def test_pointer_does_not_move_when_the_snapshot_write_fails(tmp_path: Path) -> None:
    good = ObjectSnapshotStore(FilesystemObjectStore(tmp_path))
    good.write(_snapshot(T0))
    failing = ObjectSnapshotStore(_FailingStore(tmp_path))
    with pytest.raises(StorageError):
        failing.write(_snapshot(T0 + timedelta(hours=1)))
    latest = good.latest("in-north")
    assert latest is not None and latest.cycle_time == T0


def test_pointer_retries_a_concurrent_writer(tmp_path: Path) -> None:
    objects = FilesystemObjectStore(tmp_path)
    store = ObjectSnapshotStore(objects)
    store.write(_snapshot(T0))
    calls = {"n": 0}
    original = objects.put

    def racing_put(key: str, data: bytes, **kwargs: Any):
        if key.endswith("latest.json") and calls["n"] == 0:
            calls["n"] += 1
            original(key, data, content_type="application/json")
        return original(key, data, **kwargs)

    objects.put = racing_put  # type: ignore[method-assign]
    store.write(_snapshot(T0 + timedelta(hours=1)))
    latest = store.latest("in-north")
    assert calls["n"] == 1 and latest is not None and latest.cycle_time == T0 + timedelta(hours=1)


def test_replay_prefix_never_touches_the_live_pointer(tmp_path: Path) -> None:
    objects = FilesystemObjectStore(tmp_path)
    live = ObjectSnapshotStore(objects)
    replay = ObjectSnapshotStore(objects, prefix=REPLAY_PREFIX)
    replay.write(_snapshot(T0, mode="backfill"))
    assert live.latest("in-north") is None
    assert live.get("in-north", T0, mode="backfill") is None
    assert replay.get("in-north", T0, mode="backfill") is not None


def test_a_corrupt_snapshot_fails_loudly(tmp_path: Path) -> None:
    objects = FilesystemObjectStore(tmp_path)
    objects.put(snapshot_key("in-north", T0), b'{"region_id": 1}', content_type="application/json")
    with pytest.raises(StorageError, match=r"region_snapshot\.v1"):
        ObjectSnapshotStore(objects).get("in-north", T0)


# --- artifacts + factory ------------------------------------------------------


def test_object_artifact_reader_fetches_from_the_owning_bucket(tmp_path: Path) -> None:
    models = FilesystemObjectStore(tmp_path / "models")
    models.put("forecast/v1/model.joblib", b"bytes", content_type="application/octet-stream")
    reader = ObjectArtifactReader({"p-aeropulse-models": models}, tmp_path / "cache")
    path = reader.local_path("gs://p-aeropulse-models/forecast/v1/model.joblib")
    assert path.read_bytes() == b"bytes"
    with pytest.raises(ModelServingError, match="no object store"):
        reader.local_path("gs://other-bucket/x.joblib")
    with pytest.raises(ModelServingError, match="could not fetch"):
        reader.local_path("gs://p-aeropulse-models/missing.joblib")
    with pytest.raises(ModelServingError, match="no reader"):
        reader.local_path("models/x.joblib")


def test_factory_local_filesystem(tmp_path: Path) -> None:
    storage = build_storage(Settings(data_dir=tmp_path))
    assert storage.platform == "local"
    assert set(storage.objects) == {"raw", "citizen", "models", "serving"}
    assert isinstance(storage.analytics, ParquetAnalyticsStore)
    storage.snapshots.write(_snapshot(T0))
    assert (tmp_path / "objects" / "serving" / "snapshots" / "in-north" / "latest.json").exists()


def test_factory_minio_needs_credentials(tmp_path: Path) -> None:
    with pytest.raises(StorageError, match="MINIO_ACCESS_KEY"):
        build_storage(Settings(data_dir=tmp_path, local_object_store="minio"))


def test_factory_gcp_needs_a_project_and_names_buckets_per_concern() -> None:
    with pytest.raises(StorageError, match="GCP_PROJECT"):
        build_storage(Settings(platform="gcp"))
    storage = build_storage(Settings(platform="gcp", gcp_project="aeropulse-apac"))
    assert storage.buckets == {
        "raw": "aeropulse-apac-aeropulse-raw",
        "citizen": "aeropulse-apac-aeropulse-citizen",
        "models": "aeropulse-apac-aeropulse-models",
        "serving": "aeropulse-apac-aeropulse-serving",
    }
    assert isinstance(storage.analytics, BigQueryAnalyticsStore)
