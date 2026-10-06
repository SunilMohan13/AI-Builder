"""Heuristic citizen image labels (LLD section 23). Not a trained CV model."""

from __future__ import annotations

import re

from aeropulse_contracts.citizen import CitizenReport

KEYWORDS = {
    "smoke": "smoke",
    "fire": "fire",
    "dust": "dust",
    "haze": "haze",
    "clear": "clear",
}


def classify_report(report: CitizenReport) -> CitizenReport:
    """Assign cv_class from whole-word keywords. Unknown if none match."""
    text = f"{report.observation_type} {report.notes or ''}".lower()
    for key, label in KEYWORDS.items():
        if re.search(rf"\b{key}\b", text):
            report.cv_class = label  # type: ignore[assignment]
            return report
    report.cv_class = "unknown"
    return report
