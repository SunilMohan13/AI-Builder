"""``aeropulse-cycle``: run region cycles (Cloud Run job or local cron).

    aeropulse-cycle --region in-north --mode live
    aeropulse-cycle --region all --mode live --cycle-time 2026-09-08T06:00Z
    aeropulse-cycle --region in-north --mode backfill --start 2026-09-01T00:00Z --end ...
    aeropulse-cycle --region in-north --mode replay --cycle-time 2026-09-08T06:00Z
    aeropulse-cycle --region in-north --mode history --days 60

Prints one JSON summary line per cycle. Exits 1 if any region failed.

``history`` is not a cycle: it loads provider archives for the last
``--days`` (or ``--start``/``--end``) into raw history for training, and
prints one line per chunk. It exits 1 if no source returned a record.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

from aeropulse_common.settings import get_settings
from aeropulse_observability import configure_logging
from aeropulse_regions import load_catalog
from aeropulse_storage import build_storage

from aeropulse_cycle.cycle import (
    CYCLE_MODES,
    CycleFailedError,
    CycleResult,
    CycleRunner,
    HistoryChunk,
    floor_hour,
    run_many,
)

HISTORY_MODE = "history"


def _time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _summary(result: CycleResult) -> dict[str, object]:
    snapshot = result.snapshot
    return {
        "cycle_id": result.cycle_id,
        "region_id": snapshot.region_id,
        "mode": snapshot.mode,
        "snapshot_uri": result.snapshot_uri,
        "cells": len(snapshot.cells),
        "events": len(snapshot.events),
        "plumes": len(snapshot.plumes),
        "alerts_raised": len(result.alerts_raised),
        "alerts_suppressed": result.alerts_suppressed,
        "sources": {h.source_id: h.state.value for h in snapshot.source_health},
        "served": {m.family: m.model_version for m in snapshot.served_models},
        "rows_loaded": result.rows_loaded,
    }


def _history_summary(region_id: str, chunk: HistoryChunk) -> dict[str, object]:
    return {
        "run_id": chunk.run_id,
        "region_id": region_id,
        "mode": HISTORY_MODE,
        "start": chunk.start,
        "end": chunk.end,
        "sources": {
            o.source_id: {
                "state": o.health.state.value if o.health else None,
                "records": o.health.records if o.health else 0,
                "rejected": len(o.rejected),
                "reason": o.health.reason if o.health else None,
            }
            for o in chunk.outcomes
        },
        "rows_loaded": chunk.rows_loaded,
    }


def _run_history(
    runner: CycleRunner,
    regions: list[str],
    start: datetime,
    end: datetime,
    chunk_days: int,
    sources: list[str] | None = None,
) -> int:
    records = 0
    for region in regions:
        chunks = runner.load_history(
            region, start, end, chunk=timedelta(days=chunk_days), sources=sources
        )
        for chunk in chunks:
            records += sum(o.health.records for o in chunk.outcomes if o.health)
            line = json.dumps(_history_summary(region, chunk), default=str, sort_keys=True)
            print(line, flush=True)
    return 0 if records else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aeropulse-cycle", description=__doc__)
    parser.add_argument("--region", required=True, help="region id, or 'all'")
    parser.add_argument("--mode", choices=(*CYCLE_MODES, HISTORY_MODE), default="live")
    parser.add_argument("--cycle-time", type=_time, help="defaults to the current hour")
    parser.add_argument("--start", type=_time, help="backfill/history: first cycle time")
    parser.add_argument("--end", type=_time, help="backfill/history: last cycle time")
    parser.add_argument(
        "--days", type=int, default=60, help="history: days back from now, when --start is unset"
    )
    parser.add_argument(
        "--chunk-days", type=int, default=5, help="history: days fetched and stored at a time"
    )
    parser.add_argument(
        "--sources",
        type=lambda v: [s.strip() for s in v.split(",") if s.strip()],
        help="history: comma-separated source ids to load (default: every enabled source)",
    )
    parser.add_argument("--fixtures", type=Path, default=Path("fixtures"))
    args = parser.parse_args(argv)
    if args.days <= 0 or args.chunk_days <= 0:
        parser.error("--days and --chunk-days must be positive")
    if args.sources is not None and args.mode != HISTORY_MODE:
        parser.error("--sources only applies to --mode history")

    settings = get_settings()
    configure_logging(settings, stream=sys.stderr)
    catalog = load_catalog(settings.config_dir)
    runner = CycleRunner(
        catalog,
        build_storage(settings),
        fixtures_root=args.fixtures if args.mode == "replay" else None,
    )
    regions = catalog.region_ids() if args.region == "all" else [args.region]

    if args.mode == HISTORY_MODE:
        end = floor_hour(args.end or datetime.now(UTC))
        start = args.start or (end - timedelta(days=args.days)).replace(hour=0)
        if args.sources is not None:
            unknown = sorted(
                set(args.sources)
                - {e.id for r in regions for e in catalog.get(r).sources if e.enabled}
            )
            if unknown:
                parser.error(f"--sources: not enabled in {args.region}: {', '.join(unknown)}")
        return _run_history(runner, regions, start, end, args.chunk_days, args.sources)
    if args.mode == "backfill":
        if args.start is None or args.end is None:
            parser.error("--mode backfill needs --start and --end")
        results = [r for region in regions for r in runner.backfill(region, args.start, args.end)]
        failed = False
    else:
        when = floor_hour(args.cycle_time or datetime.now(UTC))
        try:
            results = run_many(runner, regions, when, args.mode)
            failed = False
        except CycleFailedError as exc:
            results, failed = exc.results, True
            print(json.dumps({"failed": exc.failures}), file=sys.stderr)
    for result in results:
        print(json.dumps(_summary(result), default=str, sort_keys=True))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
