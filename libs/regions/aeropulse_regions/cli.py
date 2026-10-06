"""Validate packs and record station discovery without inventing coverage."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from aeropulse_observability.logging import get_logger

from aeropulse_regions.loader import PackError, load_pack, load_packs

logger = get_logger("aeropulse.regions")


def main(argv: list[str] | None = None) -> int:
    """Run ``aeropulse-region``."""
    parser = argparse.ArgumentParser(description="Validate and initialise APAC region packs")
    parser.add_argument("--config", type=Path, default=Path("config"))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate")
    init = sub.add_parser("init")
    init.add_argument("region_id")
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            packs = load_packs(args.config)
            for region_id in sorted(packs):
                logger.info("region.pack_valid", region_id=region_id)
            return 0
        summary = init_region(args.config, args.region_id)
    except PackError as exc:
        logger.error("region.pack_invalid", error=str(exc))
        return 1
    logger.info("region.init", **summary)
    return 0


def init_region(config_root: Path, region_id: str) -> dict[str, str]:
    """Write a station summary. A missing OpenAQ key is not-configured, not a fixture."""
    pack = load_pack(config_root, region_id)
    destination = config_root / "regions" / region_id / "stations.json"
    summary = {
        "region_id": pack.region_id,
        "ground_truth": "none",
        "reason": "openaq not configured",
        "stations": [],
    }
    destination.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return {
        "region_id": pack.region_id,
        "ground_truth": "none",
        "reason": "openaq not configured",
    }
