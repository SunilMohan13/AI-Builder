"""Regenerate the Open-Meteo replay fixture from the live upstream API.

The committed fixture holds verbatim upstream payloads so that replay tests
exercise the same response shape the live path parses. Regenerate it when
Open-Meteo changes its schema:

    AEROPULSE_CONNECTOR_MODE=live uv run python scripts/refresh_openmeteo_fixture.py

Requires network access. Requires no credential.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from aeropulse_connector_openmeteo import DEFAULT_SITES, OpenMeteoConnector
from aeropulse_connector_sdk.contracts import FetchRequest

FIXTURE_PATH = Path("fixtures/openmeteo/observations.json")

# Two sites keep the committed fixture small while still exercising
# multi-site fusion and the nearest-station distance feature.
FIXTURE_SITES = DEFAULT_SITES[:2]


def main() -> int:
    """Fetch live payloads and write the replay fixture.

    Returns:
        Process exit code.
    """
    if os.environ.get("AEROPULSE_CONNECTOR_MODE") != "live":
        print("refusing to run: set AEROPULSE_CONNECTOR_MODE=live", file=sys.stderr)
        return 2

    connector = OpenMeteoConnector(sites=FIXTURE_SITES, past_days=2)
    records = [r.payload for r in connector.fetch(FetchRequest())]
    document = {
        "_comment": (
            "Verbatim Open-Meteo responses captured for offline replay. "
            "Regenerate with scripts/refresh_openmeteo_fixture.py."
        ),
        "_captured_at": datetime.now(UTC).isoformat(),
        "_source": "https://open-meteo.com",
        "_attribution": "Weather and air quality data by Open-Meteo.com (CC-BY-4.0)",
        "records": records,
    }
    FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE_PATH.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")

    hours = len(records[0]["air_quality"]["hourly"]["time"]) if records else 0
    print(f"wrote {FIXTURE_PATH} sites={len(records)} hours_per_site={hours}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
