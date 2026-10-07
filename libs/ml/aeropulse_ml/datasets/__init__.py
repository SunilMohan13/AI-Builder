"""Training dataset sources and URI parsing."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlparse

from aeropulse_common.errors import DatasetError
from aeropulse_regions import RegionCatalog

from aeropulse_ml.datasets.base import NON_SERVABLE_KINDS, DatasetKind, DatasetSource
from aeropulse_ml.datasets.bigquery import BigQueryDatasetSource
from aeropulse_ml.datasets.fixture import FixtureDatasetSource
from aeropulse_ml.datasets.parquet import ParquetDatasetSource, write_parquet_dataset
from aeropulse_ml.datasets.synthetic import SyntheticDatasetSource


def open_dataset(uri: str, *, catalog: RegionCatalog) -> DatasetSource:
    """``bq://project[/dataset]``, ``parquet://path`` or a directory,
    ``fixture[://path]``, or ``synthetic://?hours=&seed=`` (test data only)."""
    if uri in {"fixture", "fixture://"}:
        return FixtureDatasetSource(catalog)
    parsed = urlparse(uri)
    if parsed.scheme == "fixture":
        return FixtureDatasetSource(catalog, root=Path(parsed.netloc + parsed.path))
    if parsed.scheme == "synthetic":
        query = parse_qs(parsed.query)
        return SyntheticDatasetSource(
            hours=int(query.get("hours", ["240"])[0]), seed=int(query.get("seed", ["7"])[0])
        )
    if parsed.scheme == "bq":
        dataset = parsed.path.strip("/") or "aeropulse_raw"
        return BigQueryDatasetSource(project=parsed.netloc, dataset=dataset)
    if parsed.scheme == "parquet":
        return ParquetDatasetSource(Path(parsed.netloc + parsed.path))
    if parsed.scheme == "" and Path(uri).is_dir():
        return ParquetDatasetSource(Path(uri))
    raise DatasetError(f"unrecognised dataset URI: {uri!r}")


__all__ = [
    "NON_SERVABLE_KINDS",
    "BigQueryDatasetSource",
    "DatasetKind",
    "DatasetSource",
    "FixtureDatasetSource",
    "ParquetDatasetSource",
    "SyntheticDatasetSource",
    "open_dataset",
    "write_parquet_dataset",
]
