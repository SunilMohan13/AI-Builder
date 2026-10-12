"""Capture a region's Demo replay fixtures from the real upstream APIs at one past hour.

The Demo recording (``scripts/generate_demo_recording.py``) runs the live cycle
at the pack's ``demo.cycle_time`` with every fetch answered from the files this
writes. Each file holds the verbatim payloads the region's own connector
plugins fetch in backfill mode for the window a live cycle at that hour would
see, cut at the hour so a replay cannot see past its own instant.

    set -a; . infrastructure/docker/.env; set +a
    uv run python scripts/capture_demo_fixtures.py --region sg-singapore --at 2023-10-07T06:00Z

Needs network access and the keys the pack names, read from the environment
and never printed. Writes ``fixtures/<source>/<region_id>.json`` and prints the
``fixture:`` lines and ``demo.cycle_time`` to put in the pack.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from aeropulse_connector_sdk.plugin import ConnectorResult
from aeropulse_connector_sdk.registry import PluginRegistry
from aeropulse_regions import load_catalog
from aeropulse_regions.context import build_context

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config"
FIXTURES = ROOT / "fixtures"

#: The window a live cycle at the hour reads, per source.
LOOKBACK = {
    # Two days of station hours: the feature builder's lags and rolling windows.
    "openaq": timedelta(hours=48),
    # The pack's ``day_range: 1``.
    "firms": timedelta(hours=24),
    # The connector's default ``past_days: 2``.
    "openmeteo": timedelta(hours=48),
}

ATTRIBUTION = {
    "openaq": "Air quality data via OpenAQ (https://openaq.org). Each location carries its "
    "own licence; provenance.provider names the upstream network.",
    "firms": "NASA FIRMS active fire data (https://firms.modaps.eosdis.nasa.gov).",
    "openmeteo": "Weather and air quality data by Open-Meteo.com (CC-BY-4.0)",
}


def _hour(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _openaq(result: ConnectorResult, at: datetime, _: Callable[..., Any]) -> dict[str, Any]:
    locations: dict[str, dict[str, Any]] = {}
    series: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for record in result.records:
        location = record.payload["location"]
        locations[str(location["id"])] = location
        key = (str(location["id"]), str(record.payload["sensor_id"]))
        for row in record.payload["hours"]:
            # An hourly mean exists only once its hour has ended.
            ended = (row.get("period") or {}).get("datetimeTo") or {}
            if ended.get("utc") and _hour(ended["utc"]) <= at:
                series.setdefault(key, []).append(row)
    return {
        "_comment": "Verbatim OpenAQ v3 responses: monitor locations from GET /v3/locations "
        "and each sensor's GET /v3/sensors/{id}/hours rows for the 48 h before the cycle "
        "hour, cut at that hour. Written by scripts/capture_demo_fixtures.py.",
        "locations": sorted(locations.values(), key=lambda loc: str(loc["id"])),
        "hours": [
            {"locations_id": int(loc), "sensor_id": sensor, "results": rows}
            for (loc, sensor), rows in sorted(series.items())
        ],
    }


def _firms(result: ConnectorResult, at: datetime, normalize: Callable[..., Any]) -> dict[str, Any]:
    start = at - LOOKBACK["firms"]
    fires = []
    for record in result.records:
        [fire] = normalize(ConnectorResult(result.source_id, [record], result.fetched_at))
        if start <= fire.observed_at <= at:
            fires.append(record.payload)
    return {
        "_comment": "Verbatim FIRMS area CSV rows over the source domain, every product the "
        "pack lists, for the 24 h before the cycle hour. Written by "
        "scripts/capture_demo_fixtures.py.",
        "fires": fires,
    }


def _cut_hourly(block: dict[str, Any], at: datetime) -> dict[str, Any]:
    hourly = block.get("hourly") or {}
    keep = [i for i, t in enumerate(hourly.get("time") or []) if _hour(t) <= at]
    return {**block, "hourly": {k: [v[i] for i in keep] for k, v in hourly.items()}}


def _openmeteo(result: ConnectorResult, at: datetime, _: Callable[..., Any]) -> dict[str, Any]:
    return {
        "_comment": "Verbatim Open-Meteo air-quality and weather responses for the pack's "
        "wind sites, from the start of the day two days before the cycle hour, cut at that "
        "hour. No issued_at: these are past hours, so the replay emits no forecast. Written "
        "by scripts/capture_demo_fixtures.py.",
        "records": [
            {
                "site": r.payload["site"],
                "air_quality": _cut_hourly(r.payload["air_quality"], at),
                "weather": _cut_hourly(r.payload["weather"], at),
            }
            for r in result.records
        ],
    }


WRITERS = {"openaq": _openaq, "firms": _firms, "openmeteo": _openmeteo}


def capture(region_id: str, at: datetime) -> dict[str, Path]:
    catalog = load_catalog(CONFIG)
    pack = catalog.get(region_id)
    registry = PluginRegistry.discover()
    written: dict[str, Path] = {}
    for entry in pack.sources:
        if not entry.enabled or entry.id not in WRITERS:
            continue
        plugin = registry.create(entry.id)
        context = build_context(
            pack, entry, mode="backfill", now=at, lookback=LOOKBACK[entry.id], run_id="capture"
        )
        issue = plugin.configuration_issue(context)
        if issue is not None:
            raise SystemExit(f"{entry.id}: {issue}")
        result = plugin.fetch(context)

        def normalize(r: ConnectorResult, plugin: Any = plugin, context: Any = context) -> Any:
            return plugin.normalize(r, context)

        document = {
            **WRITERS[entry.id](result, at, normalize),
            "_captured_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "_cycle_time": at.isoformat(),
            "_region_id": region_id,
            "_attribution": ATTRIBUTION[entry.id],
        }
        path = FIXTURES / entry.id / f"{region_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document, indent=1, ensure_ascii=False) + "\n")
        written[entry.id] = path
        print(f"{entry.id}: {len(result.records)} upstream records -> {path.relative_to(ROOT)}")
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument("--region", required=True)
    parser.add_argument("--at", required=True, type=_hour, help="cycle hour, UTC")
    args = parser.parse_args(argv)
    at = args.at.replace(minute=0, second=0, microsecond=0)
    written = capture(args.region, at)
    print("\nAdd to the pack:")
    print(f'  demo: {{ enabled: true, cycle_time: "{at:%Y-%m-%dT%H:%M:%SZ}" }}')
    for source_id, path in written.items():
        print(f"  {source_id}: fixture: {path.relative_to(FIXTURES)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
