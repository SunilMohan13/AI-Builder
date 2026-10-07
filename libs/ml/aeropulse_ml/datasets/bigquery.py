"""BigQuery dataset: ``aeropulse_raw`` tables of encoded canonical records.

The cloud SDK is loaded only when a BigQuery source is opened, so local and CI
runs need no Google credentials. Queries are parameterised; table names come
from a fixed map and identifiers are validated, so no input reaches SQL text.
"""

from __future__ import annotations

import importlib
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from aeropulse_common.errors import DatasetError

from aeropulse_ml.datasets.base import DatasetKind
from aeropulse_ml.datasets.records import batch_from_rows
from aeropulse_ml.preprocessing.batch import RecordBatch

#: Batch attribute -> table in the raw dataset (LLD APAC 6.1).
TABLES: dict[str, str] = {
    "observations": "air_quality",
    "weather": "weather",
    "forecasts": "meteo_forecast",
    "fires": "fire",
    "rasters": "raster",
}

_PROJECT = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
_DATASET = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,1023}$")

QUERY_TEMPLATE = (
    "SELECT record FROM `{project}.{dataset}.{table}` "
    "WHERE region_id = @region_id "
    "AND (@start IS NULL OR known_at >= @start) "
    "AND (@end IS NULL OR known_at <= @end)"
)

#: ``(sql, params) -> rows with a "record" field``. Injected in tests.
QueryRunner = Callable[[str, Mapping[str, Any]], Iterable[Mapping[str, Any]]]


def _client_runner(project: str) -> QueryRunner:
    try:
        bigquery = importlib.import_module("google.cloud.bigquery")
    except ImportError as exc:
        raise DatasetError(
            "google-cloud-bigquery is not installed; install the gcp extra to read bq:// datasets"
        ) from exc
    client = bigquery.Client(project=project)

    def run(sql: str, params: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
        config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("region_id", "STRING", params["region_id"]),
                bigquery.ScalarQueryParameter("start", "TIMESTAMP", params["start"]),
                bigquery.ScalarQueryParameter("end", "TIMESTAMP", params["end"]),
            ]
        )
        return client.query(sql, job_config=config).result()

    return run


@dataclass
class BigQueryDatasetSource:
    project: str
    dataset: str = "aeropulse_raw"
    runner: QueryRunner | None = None
    kind: DatasetKind = "bigquery"

    def __post_init__(self) -> None:
        if not _PROJECT.match(self.project):
            raise DatasetError(f"invalid BigQuery project id: {self.project!r}")
        if not _DATASET.match(self.dataset):
            raise DatasetError(f"invalid BigQuery dataset id: {self.dataset!r}")

    @property
    def uri(self) -> str:
        return f"bq://{self.project}/{self.dataset}"

    def load(
        self, region_id: str, *, start: datetime | None = None, end: datetime | None = None
    ) -> RecordBatch:
        run = self.runner or _client_runner(self.project)
        params = {"region_id": region_id, "start": start, "end": end}
        rows: dict[str, list[str]] = {}
        for kind, table in TABLES.items():
            sql = QUERY_TEMPLATE.format(project=self.project, dataset=self.dataset, table=table)
            rows[kind] = [str(r["record"]) for r in run(sql, params)]
        return batch_from_rows(rows)
