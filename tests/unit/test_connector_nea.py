"""NEA PM2.5 from data.gov.sg: dates, stamps, window, bbox, replay and live."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import h3
import pytest
from aeropulse_connector_nea import NeaPlugin, api_dates
from aeropulse_connector_nea.connector import NeaApiError
from aeropulse_connector_sdk.plugin import ConnectorContext, ConnectorMode, Domain
from aeropulse_connector_sdk.registry import available_source_ids
from aeropulse_regions import load_catalog

SG_BBOX = (103.6, 1.15, 104.1, 1.48)
NOW = datetime(2026, 10, 13, 6, 5, tzinfo=UTC)

META = [
    {"name": "west", "labelLocation": {"latitude": 1.35735, "longitude": 103.7}},
    {"name": "north", "labelLocation": {"latitude": 1.41803, "longitude": 103.82}},
    {"name": "far", "labelLocation": {"latitude": 3.0, "longitude": 101.0}},
]


def _body(*items: tuple[str, dict[str, Any]], token: str | None = None) -> dict[str, Any]:
    data: dict[str, Any] = {
        "regionMetadata": META,
        "items": [{"timestamp": ts, "readings": {"pm25_one_hourly": r}} for ts, r in items],
    }
    if token:
        data["paginationToken"] = token
    return {"code": 0, "data": data, "errorMsg": ""}


class FakeClient:
    def __init__(self, pages: dict[tuple[str, str | None], dict[str, Any]]) -> None:
        self.pages = pages
        self.calls: list[dict[str, Any]] = []

    def get_json(self, url: str, *, params: dict[str, Any] | None = None, **_: Any) -> Any:
        params = params or {}
        self.calls.append(params)
        return self.pages[(params["date"], params.get("paginationToken"))]


def _context(
    mode: ConnectorMode = "live", fixture: Path | None = None, **kw: Any
) -> ConnectorContext:
    return ConnectorContext(
        region_id="sg-singapore",
        bboxes={Domain.DISPLAY: SG_BBOX, Domain.SOURCE: SG_BBOX},
        mode=mode,
        now=kw.pop("now", NOW),
        window_start=kw.pop("window_start", NOW - timedelta(hours=48)),
        window_end=kw.pop("window_end", NOW),
        fixture_path=fixture,
    )


def _run(plugin: NeaPlugin, context: ConnectorContext) -> list[Any]:
    return plugin.normalize(plugin.fetch(context), context)


def test_registered_and_wired_into_singapore() -> None:
    assert "nea" in available_source_ids()
    pack = load_catalog().get("sg-singapore")
    assert "nea" in {s.id for s in pack.sources}
    assert "nea" in pack.ground_truth_sources


def test_api_dates_are_singapore_dates() -> None:
    # 15:30 UTC is 23:30 in Singapore; 16:30 UTC is the next Singapore day.
    start = datetime(2026, 10, 12, 15, 30, tzinfo=UTC)
    assert api_dates(start, start + timedelta(hours=1)) == [date(2026, 10, 12), date(2026, 10, 13)]
    assert api_dates(start, start) == [date(2026, 10, 12)]


def test_a_reading_is_stamped_when_it_is_known() -> None:
    client = FakeClient(
        {
            ("2026-10-13", None): _body(
                ("2026-10-13T13:00:00+08:00", {"west": 123, "north": 65, "far": 50}),
                ("2026-10-13T14:00:00+08:00", {"west": 120, "north": None}),
            )
        }
    )
    obs = _run(NeaPlugin(client), _context(window_start=NOW - timedelta(hours=2)))
    # 13:00 SGT (05:00 UTC) is known by 06:00 UTC; 14:00 SGT would be 07:00 UTC, after NOW.
    assert {o.observed_at for o in obs} == {datetime(2026, 10, 13, 6, tzinfo=UTC)}
    # The point outside the display bbox and the missing value are dropped.
    by_cell = {o.grid_id or h3.latlng_to_cell(o.location.lat, o.location.lon, 8): o for o in obs}
    assert set(by_cell) == {"886520ca33fffff", "88652634c9fffff"}  # west, north
    west = by_cell["886520ca33fffff"]
    assert west.measurement.parameter == "pm25" and west.measurement.unit == "ug/m3"
    assert west.measurement.value == 123.0
    assert west.source_record_id == "west_2026-10-13T06:00:00+00:00"
    assert west.provenance.provider == "NEA via data.gov.sg"


def test_live_walks_every_date_and_page_in_the_window() -> None:
    client = FakeClient(
        {
            ("2026-10-12", None): _body(("2026-10-12T23:00:00+08:00", {"west": 40}), token="t2"),
            ("2026-10-12", "t2"): _body(("2026-10-12T22:00:00+08:00", {"west": 41})),
            ("2026-10-13", None): _body(("2026-10-13T01:00:00+08:00", {"west": 42})),
        }
    )
    start = datetime(2026, 10, 12, 13, tzinfo=UTC)
    obs = _run(NeaPlugin(client), _context(window_start=start))
    assert [c["date"] for c in client.calls] == ["2026-10-12", "2026-10-12", "2026-10-13"]
    assert sorted(o.measurement.value for o in obs) == [40.0, 41.0, 42.0]


def test_hours_before_the_window_are_dropped() -> None:
    client = FakeClient(
        {
            ("2026-10-13", None): _body(
                ("2026-10-13T10:00:00+08:00", {"west": 1}),
                ("2026-10-13T12:00:00+08:00", {"west": 2}),
            )
        }
    )
    obs = _run(NeaPlugin(client), _context(window_start=datetime(2026, 10, 13, 4, tzinfo=UTC)))
    assert [o.measurement.value for o in obs] == [2.0]


def test_an_api_error_is_raised_not_swallowed() -> None:
    client = FakeClient({("2026-10-13", None): {"code": 4, "errorMsg": "bad date", "data": {}}})
    with pytest.raises(NeaApiError, match="bad date"):
        NeaPlugin(client).fetch(_context(window_start=NOW - timedelta(hours=1)))


def test_replay_reads_captured_bodies(tmp_path: Path) -> None:
    fixture = tmp_path / "nea.json"
    body = _body(("2026-10-13T12:00:00+08:00", {"west": 77}))
    fixture.write_text(json.dumps({"responses": [body]}), encoding="utf-8")
    context = _context(mode="replay", fixture=fixture)
    plugin = NeaPlugin()
    assert plugin.configuration_issue(context) is None
    (obs,) = _run(plugin, context)
    assert obs.measurement.value == 77.0
    assert plugin.configuration_issue(_context(mode="replay")) is not None
