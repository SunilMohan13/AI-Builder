"""``scripts/history.py``: the laptop history folder survives a Docker reset."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import pandas as pd
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 10, 12, 9, 30, tzinfo=UTC)


def _history() -> ModuleType:
    spec = importlib.util.spec_from_file_location("history", ROOT / "scripts" / "history.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["history"] = module
    spec.loader.exec_module(module)
    return module


history = _history()


def _raw(folder: Path, table: str, rows: list[tuple[str, str, str]], name: str) -> None:
    target = folder / "analytics" / "raw" / table
    target.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(
        [
            {"region_id": r, "known_at": t, "record": json.dumps({"source_id": s, "value": 1})}
            for r, t, s in rows
        ]
    )
    frame.to_parquet(target / f"{name}.parquet", index=False)


def _folder(tmp_path: Path) -> Path:
    folder = tmp_path / "aeropulse-data"
    _raw(
        folder,
        "air_quality",
        [
            ("in-north", "2025-10-01T00:00:00+00:00", "openaq"),
            ("in-north", "2025-10-02T00:00:00+00:00", "openaq"),
            ("in-north", "2025-10-01T00:00:00+00:00", "openmeteo_aq"),
        ],
        "a",
    )
    _raw(folder, "air_quality", [("in-north", "2026-10-01T05:00:00+00:00", "openaq")], "b")
    _raw(folder, "fire", [("sg-singapore", "2023-10-05T00:00:00+00:00", "firms")], "c")
    (folder / "models" / "runs" / "run-1").mkdir(parents=True)
    (folder / "models" / "runs" / "run-1" / "gate.json").write_text("{}")
    (folder / "objects" / "raw").mkdir(parents=True)
    (folder / "objects" / "raw" / "big.json").write_text("{}")
    return folder


def test_status_counts_rows_and_window_per_region_table_and_source(tmp_path: Path) -> None:
    rows = history.status(_folder(tmp_path))
    by_key = {(c.region_id, c.table, c.source_id): c for c in rows}
    assert set(by_key) == {
        ("in-north", "air_quality", "openaq"),
        ("in-north", "air_quality", "openmeteo_aq"),
        ("sg-singapore", "fire", "firms"),
    }
    openaq = by_key[("in-north", "air_quality", "openaq")]
    assert (openaq.rows, openaq.first, openaq.last) == (3, "2025-10-01 00:00", "2026-10-01 05:00")


def test_save_then_restore_round_trips_and_keeps_the_previous_folder(tmp_path: Path) -> None:
    folder = _folder(tmp_path)
    archive = history.save(folder, tmp_path / "backups", now=NOW)
    assert archive.name == "aeropulse-data-20261012T093000Z.tar.gz"
    with tarfile.open(archive) as tar:
        names = tar.getnames()
    assert not any(n.startswith("objects/raw") for n in names)

    (folder / "analytics" / "raw" / "fire" / "c.parquet").unlink()
    kept = history.restore(archive, folder, now=NOW)

    assert kept == tmp_path / "aeropulse-data.before-restore-20261012T093000Z"
    assert not (kept / "analytics" / "raw" / "fire" / "c.parquet").exists()
    assert (folder / "analytics" / "raw" / "fire" / "c.parquet").is_file()
    assert (folder / "models" / "runs" / "run-1" / "gate.json").is_file()
    assert len(history.status(folder)) == 3


def test_with_raw_also_archives_the_provider_responses(tmp_path: Path) -> None:
    archive = history.save(_folder(tmp_path), tmp_path / "backups", with_raw=True, now=NOW)
    with tarfile.open(archive) as tar:
        assert "objects/raw/big.json" in tar.getnames()


@pytest.mark.parametrize("name", ["../escape.txt", "/etc/escape.txt"])
def test_restore_refuses_an_archive_that_writes_outside_the_folder(
    tmp_path: Path, name: str
) -> None:
    archive = tmp_path / "evil.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        info = tarfile.TarInfo(name)
        info.size = 2
        tar.addfile(info, io.BytesIO(b"hi"))
    target = tmp_path / "data"
    with pytest.raises(SystemExit, match="unsafe path"):
        history.restore(archive, target)
    assert not target.exists()
    assert not (tmp_path / "escape.txt").exists()


def test_migrate_refuses_a_folder_that_already_has_files(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="empty folder only"):
        history.migrate(_folder(tmp_path))


def test_the_folder_resolves_as_compose_resolves_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AEROPULSE_HOST_DATA_DIR", "../../aeropulse-data")
    assert history.data_dir() == ROOT / "aeropulse-data"
    monkeypatch.setenv("AEROPULSE_HOST_DATA_DIR", str(tmp_path / "elsewhere"))
    assert history.data_dir() == tmp_path / "elsewhere"
    assert history.backup_dir() == ROOT / "aeropulse-backups"


def test_the_setting_is_read_from_the_env_file_without_other_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AEROPULSE_HOST_DATA_DIR", raising=False)
    env = tmp_path / ".env"
    env.write_text("AEROPULSE_JWT_SECRET=not-read\nAEROPULSE_HOST_DATA_DIR='/data/ap'\n")
    assert history._compose_setting("AEROPULSE_HOST_DATA_DIR", env) == "/data/ap"
    env.write_text("AEROPULSE_HOST_DATA_DIR=\n")
    assert history._compose_setting("AEROPULSE_HOST_DATA_DIR", env) == ""


def test_the_project_folders_are_kept_out_of_git_and_docker_builds() -> None:
    gitignore = (ROOT / ".gitignore").read_text().splitlines()
    dockerignore = (ROOT / ".dockerignore").read_text().splitlines()
    for name in ("aeropulse-data", "aeropulse-backups"):
        assert f"/{name}/" in gitignore
        assert name in dockerignore


def test_every_service_that_shares_the_data_mounts_the_same_laptop_folder() -> None:
    compose = yaml.safe_load((ROOT / "infrastructure" / "docker" / "compose.yaml").read_text())
    mount = "${AEROPULSE_HOST_DATA_DIR:-../../aeropulse-data}:/app/var/aeropulse"
    for service in history.SERVICES:
        spec = compose["services"][service]
        assert mount in spec["volumes"], service
        assert spec["environment"]["AEROPULSE_DATA_DIR"] == "/app/var/aeropulse", service
    assert "aeropulse-data" not in (compose.get("volumes") or {})
