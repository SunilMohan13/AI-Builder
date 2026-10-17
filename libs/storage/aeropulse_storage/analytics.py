"""Analytics storage (LLD APAC 3.5, 6.1): BigQuery, or Parquet files locally.

``load`` is keyed by ``batch_id``: loading the same batch again replaces it
(Parquet) or is a no-op (BigQuery job ids are deterministic). Callers derive
the id from the rows (:func:`batch_id`), so an identical re-run never
duplicates rows and a different one never erases the first. ``query`` takes a template id and parameters
only; free SQL is never accepted. Each template states its BigQuery SQL and
its local equivalent side by side, so the two cannot drift silently.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import pandas as pd
import pyarrow.parquet as pq

from aeropulse_storage.errors import StorageError

#: Settings: default ceiling on bytes a templated BigQuery query may bill.
DEFAULT_MAX_BYTES = 1_000_000_000
#: Rows decoded at a time when a local window read scans a file.
WINDOW_BATCH_ROWS = 20_000

#: Logical table -> (dataset suffix, table). The BigQuery dataset is
#: ``<prefix>_<suffix>``, e.g. ``aeropulse_raw.air_quality``.
TABLES: dict[str, tuple[str, str]] = {
    "raw.air_quality": ("raw", "air_quality"),
    "raw.weather": ("raw", "weather"),
    "raw.meteo_forecast": ("raw", "meteo_forecast"),
    "raw.fire": ("raw", "fire"),
    "raw.raster": ("raw", "raster"),
    "predictions.served": ("predictions", "served"),
    "predictions.shadow": ("predictions", "shadow"),
    "eval.reports": ("eval", "reports"),
    "graph.nodes": ("graph", "nodes"),
    "graph.edges": ("graph", "edges"),
    "citizen.reports": ("citizen", "reports"),
    "ops.source_health": ("ops", "source_health"),
    "ops.cycles": ("ops", "cycles"),
    "ops.alerts": ("ops", "alerts"),
}

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_BATCH = re.compile(r"^[A-Za-z0-9_\-]{1,900}$")

Row = Mapping[str, Any]
LocalQuery = Callable[[pd.DataFrame, Mapping[str, Any]], pd.DataFrame]


@dataclass(frozen=True)
class QueryTemplate:
    template_id: str
    table: str
    #: ``{table}`` is replaced by the validated fully-qualified table name.
    sql: str
    #: Parameter name -> BigQuery type (STRING, TIMESTAMP, INT64, FLOAT64).
    params: Mapping[str, str]
    local: LocalQuery
    #: Time column of a ``region_id`` / ``[start, end)`` template. Locally,
    #: only files holding rows in that window are read in full.
    window_column: str | None = None


def _in_window(frame: pd.DataFrame, params: Mapping[str, Any], column: str) -> pd.Series:
    times = pd.to_datetime(frame[column], utc=True, format="ISO8601")
    keep = frame["region_id"] == params["region_id"]
    keep &= times >= pd.Timestamp(params["start"])
    keep &= times < pd.Timestamp(params["end"])
    return keep


def _between(frame: pd.DataFrame, params: Mapping[str, Any], column: str) -> pd.DataFrame:
    if frame.empty:
        return frame
    return frame.loc[_in_window(frame, params, column)]


def _raw_window(table: str) -> QueryTemplate:
    def local(frame: pd.DataFrame, params: Mapping[str, Any]) -> pd.DataFrame:
        rows = _between(frame, params, "known_at")
        if rows.empty:
            return pd.DataFrame(columns=["record"])
        return pd.DataFrame({"record": rows["record"]})

    return QueryTemplate(
        template_id=f"{table}.window",
        table=table,
        sql=(
            "SELECT record FROM {table} WHERE region_id = @region_id "
            "AND known_at >= @start AND known_at < @end"
        ),
        params={"region_id": "STRING", "start": "TIMESTAMP", "end": "TIMESTAMP"},
        local=local,
        window_column="known_at",
    )


def _raw_source_window(table: str) -> QueryTemplate:
    """One source's rows of a raw window. Locally a text match on the record,
    a superset the caller narrows after decoding."""

    def local(frame: pd.DataFrame, params: Mapping[str, Any]) -> pd.DataFrame:
        rows = _between(frame, params, "known_at")
        if rows.empty:
            return pd.DataFrame(columns=["record"])
        marker = rf'"source_id":\s*"{re.escape(params["source_id"])}"'
        rows = rows.loc[rows["record"].astype(str).str.contains(marker, regex=True)]
        return pd.DataFrame({"record": rows["record"]})

    return QueryTemplate(
        template_id=f"{table}.source_window",
        table=table,
        sql=(
            "SELECT record FROM {table} WHERE region_id = @region_id "
            "AND known_at >= @start AND known_at < @end "
            "AND JSON_VALUE(record, '$.source_id') = @source_id"
        ),
        params={
            "region_id": "STRING",
            "source_id": "STRING",
            "start": "TIMESTAMP",
            "end": "TIMESTAMP",
        },
        local=local,
        window_column="known_at",
    )


def _latest_watermarks(frame: pd.DataFrame, params: Mapping[str, Any]) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["source_id", "watermark"])
    rows = frame.loc[(frame["region_id"] == params["region_id"]) & frame["watermark"].notna()]
    if rows.empty:
        return pd.DataFrame(columns=["source_id", "watermark"])
    rows = rows.assign(watermark=pd.to_datetime(rows["watermark"], utc=True, format="ISO8601"))
    return rows.groupby("source_id", as_index=False)["watermark"].max()


CITIZEN_COLUMNS: tuple[str, ...] = (
    "report_id",
    "region_id",
    "recorded_at",
    "created_at",
    "status",
    "moderation",
    "decision",
    "visual_class",
    "visual_class_source",
    "geo_trust",
    "corroboration",
    "matched_fire_id",
    "plume_id",
    "incident_id",
    "observed_at",
    "lat_rounded",
    "lon_rounded",
    "degraded_reasons",
)


EVAL_COLUMNS: tuple[str, ...] = (
    "run_id",
    "family",
    "model_version",
    "region_id",
    "strategy",
    "group",
    "subject",
    "metric",
    "value",
    "passed",
)


def _eval_for_region(frame: pd.DataFrame, params: Mapping[str, Any]) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=list(EVAL_COLUMNS))
    rows = frame.loc[frame["region_id"].isin([params["region_id"], "all"])]
    return rows.loc[:, [c for c in EVAL_COLUMNS if c in rows.columns]]


def _citizen_window(frame: pd.DataFrame, params: Mapping[str, Any]) -> pd.DataFrame:
    rows = _between(frame, params, "recorded_at")
    if rows.empty:
        return pd.DataFrame(columns=list(CITIZEN_COLUMNS))
    return rows.loc[:, [c for c in CITIZEN_COLUMNS if c in rows.columns]]


TEMPLATES: dict[str, QueryTemplate] = {
    t.template_id: t
    for t in (
        *(_raw_window(name) for name in TABLES if name.startswith("raw.")),
        *(_raw_source_window(name) for name in TABLES if name.startswith("raw.")),
        QueryTemplate(
            template_id="ops.source_health.watermarks",
            table="ops.source_health",
            sql=(
                "SELECT source_id, MAX(watermark) AS watermark FROM {table} "
                "WHERE region_id = @region_id AND watermark IS NOT NULL GROUP BY source_id"
            ),
            params={"region_id": "STRING"},
            local=_latest_watermarks,
        ),
        QueryTemplate(
            template_id="citizen.reports.window",
            table="citizen.reports",
            sql=(
                f"SELECT {', '.join(CITIZEN_COLUMNS)} FROM {{table}} "
                "WHERE region_id = @region_id AND recorded_at >= @start AND recorded_at < @end"
            ),
            params={"region_id": "STRING", "start": "TIMESTAMP", "end": "TIMESTAMP"},
            local=_citizen_window,
            window_column="recorded_at",
        ),
        QueryTemplate(
            template_id="eval.reports.region",
            table="eval.reports",
            sql=(
                f"SELECT {', '.join(f'`{c}`' for c in EVAL_COLUMNS)} FROM {{table}} "
                "WHERE region_id IN (@region_id, 'all')"
            ),
            params={"region_id": "STRING"},
            local=_eval_for_region,
        ),
    )
}


@runtime_checkable
class AnalyticsStore(Protocol):
    def load(self, table: str, rows: Sequence[Row], *, batch_id: str) -> int: ...

    def query(
        self, template_id: str, params: Mapping[str, Any], *, max_bytes: int = DEFAULT_MAX_BYTES
    ) -> list[dict[str, Any]]: ...


def _template(template_id: str, params: Mapping[str, Any]) -> QueryTemplate:
    try:
        template = TEMPLATES[template_id]
    except KeyError as exc:
        raise StorageError(f"unknown query template: {template_id!r}") from exc
    missing = set(template.params) - set(params)
    extra = set(params) - set(template.params)
    if missing or extra:
        raise StorageError(
            f"{template_id} takes {sorted(template.params)}; missing {sorted(missing)}, "
            f"unexpected {sorted(extra)}"
        )
    return template


def _check(table: str, batch_id: str) -> tuple[str, str]:
    if table not in TABLES:
        raise StorageError(f"unknown analytics table: {table!r}")
    if not _BATCH.match(batch_id):
        raise StorageError(f"invalid batch id: {batch_id!r}")
    return TABLES[table]


def batch_id(prefix: str, rows: Sequence[Row]) -> str:
    """``<prefix>_<hash of the rows>``: same rows, same id; any change, a new id."""
    digest = hashlib.sha256()
    for line in sorted(json.dumps(row, default=str, sort_keys=True) for row in rows):
        digest.update(line.encode())
        digest.update(b"\n")
    return f"{re.sub(r'[^A-Za-z0-9_-]', '_', prefix)}_{digest.hexdigest()[:16]}"


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Mapping | list | tuple):
        return json.dumps(value, default=str, sort_keys=True)
    return value


class ParquetAnalyticsStore:
    """``<root>/<dataset>/<table>/<batch_id>.parquet``; re-loading a batch replaces it."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def _dir(self, table: str) -> Path:
        dataset, name = TABLES[table]
        return self.root / dataset / name

    def load(self, table: str, rows: Sequence[Row], *, batch_id: str) -> int:
        _check(table, batch_id)
        if not rows:
            return 0
        target = self._dir(table) / f"{batch_id}.parquet"
        frame = pd.DataFrame([{k: _jsonable(v) for k, v in row.items()} for row in rows])
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(".parquet.tmp")
            frame.to_parquet(tmp, index=False)
            tmp.replace(target)
        except OSError as exc:
            raise StorageError(f"could not load {table} batch {batch_id}: {exc}") from exc
        return len(frame)

    def read(self, table: str) -> pd.DataFrame:
        """Every row of a table (local inspection and tests)."""
        if table not in TABLES:
            raise StorageError(f"unknown analytics table: {table!r}")
        files = sorted(self._dir(table).glob("*.parquet"))
        if not files:
            return pd.DataFrame()
        return pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)

    def _read_window(self, template: QueryTemplate, params: Mapping[str, Any]) -> pd.DataFrame:
        """The template's rows, file by file, reading a file in full only if it
        holds some of the window.

        A year of raw history is several GB once decoded, far over the cycle
        and API memory limits; a cycle needs 72 h of it. Window templates are
        row filters, so applying one per file keeps only its result in memory.
        """
        column = template.window_column
        assert column is not None
        parts: list[pd.DataFrame] = []
        for path in sorted(self._dir(template.table).glob("*.parquet")):
            keep = _in_window(pd.read_parquet(path, columns=["region_id", column]), params, column)
            if not keep.any():
                continue
            # A history file can hold months of a region's model grid in one
            # row group; read it in slices so only the kept rows accumulate.
            for batch in pq.ParquetFile(path).iter_batches(batch_size=WINDOW_BATCH_ROWS):
                part = template.local(batch.to_pandas(), params)
                if not part.empty:
                    parts.append(part)
        if not parts:
            return template.local(pd.DataFrame(), params)
        return pd.concat(parts, ignore_index=True)

    def query(
        self, template_id: str, params: Mapping[str, Any], *, max_bytes: int = DEFAULT_MAX_BYTES
    ) -> list[dict[str, Any]]:
        template = _template(template_id, params)
        result = (
            template.local(self.read(template.table), params)
            if template.window_column is None
            else self._read_window(template, params)
        )
        return [
            {k: (v.to_pydatetime() if isinstance(v, pd.Timestamp) else v) for k, v in row.items()}
            for row in result.to_dict(orient="records")
        ]


class BigQueryAnalyticsStore:
    """Batch load jobs (never streaming inserts) and parameterised templates."""

    def __init__(self, project: str, *, prefix: str = "aeropulse", client: Any | None = None):
        if not re.match(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$", project):
            raise StorageError(f"invalid BigQuery project id: {project!r}")
        if not _IDENT.match(prefix):
            raise StorageError(f"invalid BigQuery dataset prefix: {prefix!r}")
        self.project = project
        self.prefix = prefix
        self._client = client

    def _bq(self) -> Any:
        try:
            return importlib.import_module("google.cloud.bigquery")
        except ImportError as exc:
            raise StorageError(
                "google-cloud-bigquery is not installed; install aeropulse-storage[gcp]"
            ) from exc

    def client(self) -> Any:
        if self._client is None:
            self._client = self._bq().Client(project=self.project)
        return self._client

    def table_id(self, table: str) -> str:
        if table not in TABLES:
            raise StorageError(f"unknown analytics table: {table!r}")
        dataset, name = TABLES[table]
        return f"{self.project}.{self.prefix}_{dataset}.{name}"

    def load(self, table: str, rows: Sequence[Row], *, batch_id: str) -> int:
        _check(table, batch_id)
        if not rows:
            return 0
        bigquery = self._bq()
        payload = [{k: _jsonable(v) for k, v in row.items()} for row in rows]
        config = bigquery.LoadJobConfig(
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
            write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        )
        job_id = f"aeropulse_{table.replace('.', '_')}_{batch_id}"
        exceptions = _bq_exceptions()
        try:
            job = self.client().load_table_from_json(
                payload, self.table_id(table), job_config=config, job_id=job_id
            )
            job.result()
        except exceptions.Conflict:
            return 0
        except exceptions.GoogleAPICallError as exc:
            raise StorageError(f"could not load {table} batch {batch_id}: {exc}") from exc
        return len(payload)

    def query(
        self, template_id: str, params: Mapping[str, Any], *, max_bytes: int = DEFAULT_MAX_BYTES
    ) -> list[dict[str, Any]]:
        template = _template(template_id, params)
        bigquery = self._bq()
        sql = template.sql.format(table=f"`{self.table_id(template.table)}`")
        config = bigquery.QueryJobConfig(
            maximum_bytes_billed=max_bytes,
            query_parameters=[
                bigquery.ScalarQueryParameter(name, kind, params[name])
                for name, kind in template.params.items()
            ],
        )
        exceptions = _bq_exceptions()
        try:
            rows = self.client().query(sql, job_config=config).result()
        except exceptions.NotFound as exc:
            # Tables are created by their first batch load (no DDL), so a table
            # nothing has loaded into yet has no rows, as in the Parquet store.
            # A missing dataset is a deployment error and still fails.
            if not self._dataset_exists(template.table):
                raise StorageError(f"query {template_id} failed: {exc}") from exc
            return []
        except exceptions.GoogleAPICallError as exc:
            raise StorageError(f"query {template_id} failed: {exc}") from exc
        return [dict(row.items()) for row in rows]

    def _dataset_exists(self, table: str) -> bool:
        dataset, _ = TABLES[table]
        try:
            self.client().get_dataset(f"{self.project}.{self.prefix}_{dataset}")
        except _bq_exceptions().NotFound:
            return False
        return True


def _bq_exceptions() -> Any:
    return importlib.import_module("google.api_core.exceptions")
