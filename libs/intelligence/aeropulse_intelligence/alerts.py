"""Create canonical alerts from events (LLD section 29). Log channel only."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from aeropulse_common.ids import new_ulid
from aeropulse_contracts.alert import Alert
from aeropulse_contracts.event import EventEvidence, PollutionEvent


def alert_from_event(event: PollutionEvent, evidence: list[EventEvidence]) -> Alert | None:
    """Return an alert for HIGH/CRITICAL events; skip quieter states."""
    if event.severity.value not in {"HIGH", "CRITICAL"}:
        return None
    if event.status.value in {"REJECTED", "RESOLVED"}:
        return None
    now = datetime.now(UTC)
    return Alert(
        alert_id=new_ulid("al"),
        event_id=event.event_id,
        severity=event.severity.value.lower(),
        recipient_group="operators",
        message_template="pollution_event_high",
        message=(
            f"{event.severity.value} pollution event {event.event_id} "
            f"status={event.status.value} overall={event.overall_confidence:.2f}"
        ),
        evidence=[{"evidence_id": e.evidence_id, "type": e.evidence_type} for e in evidence],
        created_at=now,
        expires_at=now + timedelta(hours=12),
        channel="log",
    )
