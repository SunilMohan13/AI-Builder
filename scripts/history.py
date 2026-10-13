"""Keep the loaded history on the laptop: migrate, save, restore, status.

The api, cycle and citizen-analyzer containers share one laptop folder,
``AEROPULSE_HOST_DATA_DIR`` (default ``aeropulse-data/`` at the repository
root, git-ignored), mounted at ``/app/var/aeropulse``. It holds the Parquet
history the trainers read, the trained runs and the snapshots. A Docker reset
or ``down -v`` cannot touch it.

    uv run python scripts/history.py migrate          # once: copy the old Docker volume
    uv run python scripts/history.py status           # what is loaded, per region and source
    uv run python scripts/history.py save             # dated archive in aeropulse-backups/
    uv run python scripts/history.py restore <file>   # put an archive back

Reads no keys and writes no secrets: archives hold data files only. From
``infrastructure/docker/.env`` it reads ``AEROPULSE_HOST_DATA_DIR`` and nothing else.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tarfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

#: The Docker volume the Compose stack used before the laptop folder.
OLD_VOLUME = "aeropulse_aeropulse-data"
#: Services that read or write the folder; restore waits for them to stop.
SERVICES = ("api", "cycle", "citizen-analyzer")
#: What an archive holds by default: history, trained runs, snapshots, citizen uploads.
SAVED = ("analytics", "models", "objects/serving", "objects/citizen")
#: The raw provider responses: an audit trail, not read by training or serving.
RAW_ARCHIVE = "objects/raw"

REPO = Path(__file__).resolve().parents[1]
#: Compose resolves a relative AEROPULSE_HOST_DATA_DIR from the compose file's folder.
COMPOSE_DIR = REPO / "infrastructure" / "docker"

_SOURCE = re.compile(r'"source_id":\s*"([^"]+)"')


def _compose_setting(name: str, env_file: Path = COMPOSE_DIR / ".env") -> str:
    """``name`` from the environment, else from the Compose env file; empty if unset."""
    if os.environ.get(name):
        return os.environ[name]
    if not env_file.is_file():
        return ""
    for line in env_file.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() == name:
            return value.strip().strip("'\"")
    return ""


def data_dir() -> Path:
    """The folder Compose mounts: the same default and the same relative-path rule."""
    configured = _compose_setting("AEROPULSE_HOST_DATA_DIR")
    if not configured:
        return REPO / "aeropulse-data"
    path = Path(configured).expanduser()
    return path if path.is_absolute() else (COMPOSE_DIR / path).resolve()


def backup_dir() -> Path:
    return REPO / "aeropulse-backups"


def _stamp(now: datetime) -> str:
    return now.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def _size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def _human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def save(
    source: Path, target_dir: Path, *, with_raw: bool = False, now: datetime | None = None
) -> Path:
    """Write ``aeropulse-data-<UTC>.tar.gz`` of the parts that exist; return its path."""
    parts = [*SAVED, RAW_ARCHIVE] if with_raw else list(SAVED)
    present = [p for p in parts if (source / p).exists()]
    if not present:
        raise SystemExit(f"nothing to save: {source} has none of {', '.join(parts)}")
    target_dir.mkdir(parents=True, exist_ok=True)
    archive = target_dir / f"aeropulse-data-{_stamp(now or datetime.now(UTC))}.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        for part in present:
            tar.add(source / part, arcname=part)
    return archive


def _running(services: Sequence[str]) -> list[str]:
    """Compose services of this project that are running; empty when Docker is absent."""
    if shutil.which("docker") is None:
        return []
    done = subprocess.run(
        [
            "docker",
            "ps",
            "--filter",
            "label=com.docker.compose.project=aeropulse",
            "--format",
            '{{.Label "com.docker.compose.service"}}',
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0:
        return []
    return sorted({s for s in done.stdout.split() if s in services})


def restore(archive: Path, target: Path, *, now: datetime | None = None) -> Path | None:
    """Extract ``archive`` into ``target``; the previous folder is moved aside, not deleted."""
    if not archive.is_file():
        raise SystemExit(f"no such archive: {archive}")
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar.getmembers():
            name = Path(member.name)
            if name.is_absolute() or ".." in name.parts:
                raise SystemExit(f"refusing unsafe path in archive: {member.name}")
        kept = None
        if target.exists() and any(target.iterdir()):
            kept = target.with_name(
                f"{target.name}.before-restore-{_stamp(now or datetime.now(UTC))}"
            )
            target.rename(kept)
        target.mkdir(parents=True, exist_ok=True)
        tar.extractall(target, filter="data")
    return kept


@dataclass(frozen=True)
class Coverage:
    region_id: str
    table: str
    source_id: str
    rows: int
    first: str
    last: str


def status(source: Path) -> list[Coverage]:
    """Rows and the first and last ``known_at`` per region, raw table and source."""
    import pandas as pd

    totals: dict[tuple[str, str, str], list] = {}
    for table_dir in sorted((source / "analytics" / "raw").glob("*")):
        for path in sorted(table_dir.glob("*.parquet")):
            frame = pd.read_parquet(path, columns=["region_id", "known_at", "record"])
            if frame.empty:
                continue
            frame["source_id"] = [
                (m.group(1) if (m := _SOURCE.search(str(r))) else "?") for r in frame["record"]
            ]
            frame["known_at"] = pd.to_datetime(frame["known_at"], utc=True, format="ISO8601")
            grouped = (
                frame.groupby(["region_id", "source_id"])["known_at"]
                .agg(["size", "min", "max"])
                .reset_index()
            )
            for region_id, source_id, size, low, high in grouped.itertuples(index=False):
                key = (str(region_id), table_dir.name, str(source_id))
                if key in totals:
                    count, first, last = totals[key]
                    totals[key] = [count + int(size), min(first, low), max(last, high)]
                else:
                    totals[key] = [int(size), low, high]
    return [
        Coverage(r, t, s, int(n), f"{first:%Y-%m-%d %H:%M}", f"{last:%Y-%m-%d %H:%M}")
        for (r, t, s), (n, first, last) in sorted(totals.items())
    ]


def _print_status(rows: Iterable[Coverage], source: Path) -> None:
    rows = list(rows)
    print(f"{source}  ({_human(_size(source)) if source.exists() else 'missing'})")
    if not rows:
        print("  no raw history loaded")
        return
    print(f"  {'region':14} {'table':12} {'source':12} {'rows':>10}  first             last")
    for c in rows:
        print(f"  {c.region_id:14} {c.table:12} {c.source_id:12} {c.rows:>10}  {c.first}  {c.last}")
    runs = sorted((source / "models" / "runs").glob("*/gate.json"))
    print(f"  trained runs: {len(runs)}")


def migrate(target: Path, volume: str = OLD_VOLUME) -> None:
    """Copy the old Docker volume into ``target`` with a throwaway container."""
    if target.exists() and any(target.iterdir()):
        raise SystemExit(f"{target} already has files; migrate copies into an empty folder only")
    if shutil.which("docker") is None:
        raise SystemExit("docker is not on PATH")
    found = subprocess.run(
        ["docker", "volume", "inspect", volume], capture_output=True, text=True, check=False
    )
    if found.returncode != 0:
        raise SystemExit(f"no Docker volume named {volume}; nothing to migrate")
    running = _running(SERVICES)
    if running:
        raise SystemExit(f"stop these first (dc down): {', '.join(running)}")
    target.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{volume}:/from:ro",
            "-v",
            f"{target}:/to",
            "alpine",
            "sh",
            "-c",
            "cp -a /from/. /to/",
        ],
        check=True,
    )
    print(f"copied {volume} -> {target} ({_human(_size(target))})")
    print(f"once you have checked it, remove the old volume with: docker volume rm {volume}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate", help="copy the old Docker volume into the laptop folder (once)")
    sub.add_parser("status", help="what is loaded, per region and source")
    save_cmd = sub.add_parser("save", help="write a dated archive")
    save_cmd.add_argument("--to", type=Path, default=None, help="default aeropulse-backups/")
    save_cmd.add_argument(
        "--with-raw",
        action="store_true",
        help=f"also keep {RAW_ARCHIVE} (raw provider responses; large, not needed to train)",
    )
    restore_cmd = sub.add_parser("restore", help="put an archive back (stop the stack first)")
    restore_cmd.add_argument("archive", type=Path)
    args = parser.parse_args(argv)

    folder = data_dir()
    if args.command == "migrate":
        migrate(folder)
    elif args.command == "status":
        _print_status(status(folder), folder)
    elif args.command == "save":
        archive = save(folder, args.to or backup_dir(), with_raw=args.with_raw)
        print(f"wrote {archive} ({_human(_size(archive))})")
    elif args.command == "restore":
        running = _running(SERVICES)
        if running:
            raise SystemExit(f"stop these first (dc down): {', '.join(running)}")
        kept = restore(args.archive.expanduser(), folder)
        if kept is not None:
            print(f"previous folder kept at {kept}")
        print(f"restored {args.archive} -> {folder}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
