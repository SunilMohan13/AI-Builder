"""Scheduled drift evaluation and alerting (LLD §46, gap analysis P1-12).

``GET /api/v1/drift`` already computes PSI and KS between two windows, but
only when somebody asks. Nobody asks at 3am, which is when a connector
changes its units or a station goes offline and the feature distribution
moves under a model that keeps answering confidently. This module is the
scheduled half: it sweeps every whitelisted signal on an interval, compares a
recent window against a reference window, and emits a structured alert for
anything that moved.

Two limits are stated rather than hidden, because both bound what a green
result here is worth:

* **This is distribution drift, not error drift.** It detects that inputs
  changed. It cannot detect that predictions became wrong while inputs stayed
  put, which needs delayed ground truth the system does not yet persist.
* **A moved distribution is not automatically a problem.** Winter genuinely
  looks different from monsoon. The alert says "this changed"; deciding
  whether that is seasonality or a broken feed is an operator's judgement,
  so the payload carries the numbers needed to make it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from aeropulse_observability.logging import get_logger

from aeropulse_ml.drift import distribution_drift

logger = get_logger("aeropulse.drift")

#: Statuses that warrant an operator alert. STABLE and INSUFFICIENT_DATA do
#: not: the second is a coverage problem, reported in the summary rather than
#: paged on, because alerting on "not enough rows yet" trains people to
#: ignore the channel.
ALERTING_STATUSES = frozenset({"WARNING", "DRIFT"})

#: Default comparison geometry: the last 24 hours against the 7 days before
#: it. Long enough that the reference is not itself noise, short enough that a
#: real shift is not diluted by weeks of normal data.
DEFAULT_CURRENT_HOURS = 24
DEFAULT_REFERENCE_HOURS = 168


class DriftValueReader(Protocol):
    """Reads one bounded numeric signal over a time window."""

    def values(
        self,
        signal: str,
        start: datetime,
        end: datetime,
        grid_id: str | None,
        model_version: str | None,
        limit: int,
    ) -> list[float]: ...


@dataclass(frozen=True)
class DriftFinding:
    """One signal's drift verdict over one comparison.

    Attributes:
        signal: Whitelisted signal name.
        status: ``STABLE``, ``WARNING``, ``DRIFT`` or ``INSUFFICIENT_DATA``.
        psi: Population stability index, None when not computable.
        ks_statistic: Two-sample KS statistic, None when not computable.
        reference_n: Rows in the reference window.
        current_n: Rows in the current window.
        detail: Full metric payload, for the alert body.
    """

    signal: str
    status: str
    psi: float | None
    ks_statistic: float | None
    reference_n: int
    current_n: int
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def alerting(self) -> bool:
        """Return True when this finding should reach an operator."""
        return self.status in ALERTING_STATUSES


@dataclass
class DriftReport:
    """Outcome of one scheduled sweep.

    Attributes:
        generated_at: When the sweep ran.
        current_window: ``(start, end)`` of the window under test.
        reference_window: ``(start, end)`` it was compared against.
        findings: One per signal evaluated.
    """

    generated_at: datetime
    current_window: tuple[datetime, datetime]
    reference_window: tuple[datetime, datetime]
    findings: list[DriftFinding] = field(default_factory=list)

    @property
    def alerts(self) -> list[DriftFinding]:
        """Return only the findings that warrant an operator alert."""
        return [f for f in self.findings if f.alerting]

    @property
    def unevaluated(self) -> list[DriftFinding]:
        """Return signals that had too little data to judge.

        Worth surfacing separately: a signal that is *always* here has
        silently stopped being monitored, which looks identical to "stable"
        if the two are merged.
        """
        return [f for f in self.findings if f.status == "INSUFFICIENT_DATA"]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable summary."""
        return {
            "generated_at": self.generated_at.isoformat(),
            "current_window": [d.isoformat() for d in self.current_window],
            "reference_window": [d.isoformat() for d in self.reference_window],
            "signals_evaluated": len(self.findings),
            "alerting": len(self.alerts),
            "unevaluated": len(self.unevaluated),
            "findings": [
                {
                    "signal": f.signal,
                    "status": f.status,
                    "psi": f.psi,
                    "ks_statistic": f.ks_statistic,
                    "reference_n": f.reference_n,
                    "current_n": f.current_n,
                }
                for f in self.findings
            ],
            "limitations": [
                "distribution drift only; prediction error drift requires delayed "
                "ground truth that is not yet persisted",
                "a moved distribution may be seasonality rather than a defect",
            ],
        }


def evaluate_drift(
    reader: DriftValueReader,
    signals: Sequence[str],
    *,
    now: datetime | None = None,
    current_hours: int = DEFAULT_CURRENT_HOURS,
    reference_hours: int = DEFAULT_REFERENCE_HOURS,
    grid_id: str | None = None,
    limit: int = 5000,
    min_samples: int = 30,
) -> DriftReport:
    """Compare a recent window against a reference window for every signal.

    Args:
        reader: Source of windowed values.
        signals: Whitelisted signal names to evaluate.
        now: End of the current window. Defaults to the wall clock.
        current_hours: Length of the window under test.
        reference_hours: Length of the preceding reference window.
        grid_id: Restrict to one cell, or None for all.
        limit: Maximum rows per window.
        min_samples: Rows required in each window before a verdict is given.
            Below it the signal reports ``INSUFFICIENT_DATA`` rather than a
            statistic computed from too little data to mean anything.

    Returns:
        A :class:`DriftReport`. A reader failure on one signal is recorded as
        ``INSUFFICIENT_DATA`` rather than aborting the sweep, so one bad
        column cannot hide drift in every other.
    """
    end = now or datetime.now(UTC)
    current_start = end - timedelta(hours=current_hours)
    reference_start = current_start - timedelta(hours=reference_hours)

    findings: list[DriftFinding] = []
    for signal in signals:
        try:
            reference = reader.values(signal, reference_start, current_start, grid_id, None, limit)
            current = reader.values(signal, current_start, end, grid_id, None, limit)
        except Exception as exc:
            logger.warning("drift.signal_unreadable", signal=signal, error=str(exc))
            findings.append(
                DriftFinding(
                    signal=signal,
                    status="INSUFFICIENT_DATA",
                    psi=None,
                    ks_statistic=None,
                    reference_n=0,
                    current_n=0,
                    detail={"error": f"{type(exc).__name__}: {exc}"},
                )
            )
            continue

        metrics = distribution_drift(reference, current, min_samples=min_samples)
        findings.append(
            DriftFinding(
                signal=signal,
                status=str(metrics["status"]),
                psi=metrics.get("psi"),
                ks_statistic=metrics.get("ks_statistic"),
                reference_n=int(metrics["reference_n"]),
                current_n=int(metrics["current_n"]),
                detail=metrics,
            )
        )

    report = DriftReport(
        generated_at=end,
        current_window=(current_start, end),
        reference_window=(reference_start, current_start),
        findings=findings,
    )
    _emit(report)
    return report


def _emit(report: DriftReport) -> None:
    """Log the sweep outcome, one structured line per alerting signal.

    Alerting goes through structlog rather than a bespoke channel so it
    inherits the existing correlation and trace binding, and so a deployment
    routes it with the same log pipeline as everything else. A dedicated
    notification adapter is the alerting layer's job, not this module's.

    Args:
        report: Sweep outcome.
    """
    logger.info(
        "drift.sweep_complete",
        signals_evaluated=len(report.findings),
        alerting=len(report.alerts),
        unevaluated=len(report.unevaluated),
    )
    for finding in report.alerts:
        logger.warning(
            "drift.detected",
            signal=finding.signal,
            status=finding.status,
            psi=finding.psi,
            ks_statistic=finding.ks_statistic,
            reference_n=finding.reference_n,
            current_n=finding.current_n,
        )
    for finding in report.unevaluated:
        logger.info(
            "drift.not_evaluable",
            signal=finding.signal,
            reference_n=finding.reference_n,
            current_n=finding.current_n,
        )
