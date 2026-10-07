"""Provenance classes and field-status markers shared by every served value (LLD APAC 2.2)."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class ProvenanceClass(StrEnum):
    """What kind of thing produced a value.

    The UI shows one badge per class and the grounding validator refuses an
    answer that presents a non-``MEASURED`` value with measurement wording.
    """

    MEASURED = "measured"
    MODEL_DERIVED = "model_derived"
    PREDICTED = "predicted"
    SIMULATED = "simulated"
    HEURISTIC = "heuristic"
    AI_OBSERVATION = "ai_observation"
    CITIZEN = "citizen"


#: Classes that must never be worded as a measurement.
NON_MEASURED_CLASSES = frozenset(
    {
        ProvenanceClass.SIMULATED,
        ProvenanceClass.HEURISTIC,
        ProvenanceClass.AI_OBSERVATION,
    }
)


class FieldStatus(BaseModel):
    """Why a field is ``null``. The UI renders "—" with ``reason``."""

    model_config = {"extra": "forbid"}

    field: str
    reason: str
