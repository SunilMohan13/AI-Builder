"""Heuristic citizen CV tests."""

from datetime import UTC, datetime

from aeropulse_contracts.citizen import CitizenReport
from aeropulse_intelligence.cv import classify_report


def test_keyword_smoke() -> None:
    report = CitizenReport(
        report_id="cit_1",
        lat=28.6,
        lon=77.2,
        observed_at=datetime.now(UTC),
        observation_type="photo",
        notes="thick smoke over the field",
    )
    classify_report(report)
    assert report.cv_class == "smoke"


def test_unknown_without_keyword() -> None:
    report = CitizenReport(
        report_id="cit_2",
        lat=28.6,
        lon=77.2,
        observed_at=datetime.now(UTC),
        observation_type="other",
        notes="unclear sky",
    )
    classify_report(report)
    assert report.cv_class == "unknown"
