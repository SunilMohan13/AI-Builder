"""ML evaluation API (LLD APAC 7.6, 12.1): metric rows from ``aeropulse_eval.reports``.

Rows are what a training or evaluation run measured; nothing here is
computed or estimated by the API. A family with no rows says so.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Annotated, Any

from aeropulse_auth.jwt import TokenClaims
from fastapi import APIRouter, Depends, Query

from aeropulse_api.deps import get_claims
from aeropulse_api.platform import ApiPlatform, get_platform, region_id_param

router = APIRouter(prefix="/api/v1/ml", tags=["ml"])


@router.get("/evaluation")
def evaluation(
    _claims: Annotated[TokenClaims, Depends(get_claims)],
    platform: Annotated[ApiPlatform, Depends(get_platform)],
    region_id: Annotated[str, Depends(region_id_param)],
    family: Annotated[str | None, Query(max_length=64)] = None,
) -> dict[str, Any]:
    rows = platform.storage.analytics.query(
        "eval.reports.region",
        {"region_id": region_id},
        max_bytes=platform.storage.max_query_bytes,
    )
    if family is not None:
        rows = [r for r in rows if r.get("family") == family]
    runs: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        runs[(str(row["family"]), str(row["run_id"]), str(row["model_version"]))].append(row)
    items = [
        {
            "family": fam,
            "run_id": run_id,
            "model_version": version,
            "region_id": region_id,
            "passed": any(
                bool(r.get("passed")) for r in metrics if r.get("region_id") == region_id
            ),
            "metrics": [
                {
                    "strategy": r.get("strategy"),
                    "group": r.get("group"),
                    "subject": r.get("subject"),
                    "metric": r.get("metric"),
                    "value": r.get("value"),
                    "passed": bool(r.get("passed")),
                    "region_id": r.get("region_id"),
                }
                for r in metrics
            ],
        }
        for (fam, run_id, version), metrics in sorted(runs.items())
    ]
    body: dict[str, Any] = {
        "items": items,
        "total": len(items),
        "limit": None,
        "offset": 0,
        "region_id": region_id,
        "family": family,
        "field_status": [],
    }
    if not items:
        body["field_status"] = [
            {
                "field": "items",
                "reason": (
                    f"no evaluation rows for {family or 'any family'} in {region_id}; run "
                    "`aeropulse-ml train --family ... --load-eval` or "
                    "`aeropulse-citizen eval --load`"
                ),
            }
        ]
    return body
