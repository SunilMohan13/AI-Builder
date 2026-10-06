"""Compose E2E checks against the local stack. Prints pass/fail only."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

from aeropulse_auth import Role, encode_token

TOKEN = encode_token("e2e", [Role.VIEWER])
BASE = "http://127.0.0.1:8000"


def get(path: str, **query):
    qs = "&".join(f"{k}={v}" for k, v in query.items())
    url = f"{BASE}{path}" + (f"?{qs}" if qs else "")
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read().decode()
            return resp.status, json.loads(body) if body else None
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()[:400]


def post(path: str, payload: dict):
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=json.dumps(payload).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()[:400]


def main() -> int:
    lines: list[str] = []
    status, _health = get("/health")
    lines.append(f"GET /health -> {status}")
    if status != 200:
        print("\n".join(lines))
        return 1

    status, sources = get("/api/v1/sources", limit=50)
    if status != 200 or not isinstance(sources, dict):
        lines.append(f"GET /sources FAIL {status}")
        print("\n".join(lines))
        return 1
    items = sources["items"]
    ids = {row["source_id"] for row in items}
    imd = next(row for row in items if row["source_id"] == "imd")
    openaq = next(row for row in items if row["source_id"] == "openaq")
    lines.append(
        "GET /sources -> "
        f"n={len(items)} total={sources['total']} "
        f"imd_enabled={imd['enabled']} openaq_status={openaq.get('status')} "
        f"openaq_records={openaq.get('records_per_run')}"
    )
    if not {"openaq", "openmeteo", "firms"} <= ids:
        print("\n".join([*lines, "missing live-capable sources"]))
        return 1
    if imd["enabled"] is not False:
        print("\n".join([*lines, "IMD should be disabled"]))
        return 1
    if openaq.get("records_per_run") != 4:
        print("\n".join([*lines, "openaq telemetry missing"]))
        return 1

    status, events = get("/api/v1/events", limit=5)
    lines.append(
        f"GET /events -> {status} total={events.get('total') if isinstance(events, dict) else '?'}"
    )
    if status != 200 or not events["total"]:
        print("\n".join(lines))
        return 1
    event_id = events["items"][0]["event_id"]

    status, explain = post("/api/v1/copilot/explain-event", {"event_id": event_id})
    answer = explain.get("answer", "") if isinstance(explain, dict) else ""
    lines.append(
        f"POST /explain-event -> {status} llm_used={explain.get('llm_used') if isinstance(explain, dict) else '?'}"
    )
    if status != 200 or "No event found" in answer:
        print("\n".join([*lines, f"explain failed: {answer[:120]}"]))
        return 1

    status, feats = get("/api/v1/grid-features", limit=5)
    lines.append(
        f"GET /grid-features -> {status} total={feats.get('total') if isinstance(feats, dict) else '?'}"
    )
    if status == 200 and feats.get("items"):
        grid_id = feats["items"][0]["grid_id"]
        status, hist = get(f"/api/v1/grid-features/{grid_id}/history", limit=48)
        n = hist.get("total") if isinstance(hist, dict) else "?"
        lines.append(f"GET /grid-features/{{id}}/history -> {status} total={n}")
        if status != 200:
            print("\n".join(lines))
            return 1

    status, citizens = get("/api/v1/citizen/reports", limit=2, offset=0)
    lines.append(f"GET /citizen/reports -> {status}")
    if status != 200 or not {"items", "total", "limit", "offset"} <= set(citizens):
        print("\n".join([*lines, "citizen list shape wrong"]))
        return 1

    req = urllib.request.Request("http://127.0.0.1:9090/metrics")
    with urllib.request.urlopen(req, timeout=5) as resp:
        body = resp.read().decode()
    lines.append(f"GET worker /metrics -> {resp.status} bytes={len(body)}")
    if "process_cpu_seconds_total" not in body and "python_info" not in body:
        print("\n".join([*lines, "worker metrics empty"]))
        return 1

    print("\n".join(lines))
    print("E2E_API_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
