"""``aeropulse-cycle``: run region cycles (Cloud Run job or local cron).

    aeropulse-cycle --region in-north --mode live
    aeropulse-cycle --region all --mode live --cycle-time 2026-09-08T06:00Z
    aeropulse-cycle --region in-north --mode backfill --start 2026-09-01T00:00Z --end ...
    aeropulse-cycle --region in-north --mode replay --cycle-time 2026-09-08T06:00Z

Prints one JSON summary line per cycle. Exits 1 if any region failed.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
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
    floor_hour,
    run_many,
)


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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aeropulse-cycle", description=__doc__)
    parser.add_argument("--region", required=True, help="region id, or 'all'")
    parser.add_argument("--mode", choices=CYCLE_MODES, default="live")
    parser.add_argument("--cycle-time", type=_time, help="defaults to the current hour")
    parser.add_argument("--start", type=_time, help="backfill: first cycle time")
    parser.add_argument("--end", type=_time, help="backfill: last cycle time")
    parser.add_argument("--fixtures", type=Path, default=Path("fixtures"))
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(settings, stream=sys.stderr)
    catalog = load_catalog(settings.config_dir)
    runner = CycleRunner(
        catalog,
        build_storage(settings),
        fixtures_root=args.fixtures if args.mode == "replay" else None,
    )
    regions = catalog.region_ids() if args.region == "all" else [args.region]

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
