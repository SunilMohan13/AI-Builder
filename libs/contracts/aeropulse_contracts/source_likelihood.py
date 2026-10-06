"""Hazard-profile source ranking (source_likelihood.v2).

Scores do not sum to 1 and are never a calibrated probability. No gold set
exists, so ``calibrated`` is fixed false.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from aeropulse_contracts.observation import ProvenanceClass


class EvidenceItem(BaseModel):
    """One signal that contributed to a source ranking."""

    model_config = {"extra": "forbid"}

    source_id: str
    name: str
    value: float
    unit: str
    observed_at: datetime


class SourceScore(BaseModel):
    """One hazard-profile class and its heuristic score."""

    model_config = {"extra": "forbid"}

    source_class: str
    score: float = Field(..., ge=0.0, le=1.0)
    contributing_signals: list[str] = Field(default_factory=list)


class SourceLikelihoodV2(BaseModel):
    """Ranked source classes for one cell-hour. Not a percentage mix."""

    model_config = {"extra": "forbid"}

    schema_version: Literal["source_likelihood.v2"] = "source_likelihood.v2"
    region_id: str
    grid_id: str
    valid_at: datetime
    method_version: str
    provenance_class: Literal[ProvenanceClass.HEURISTIC] = ProvenanceClass.HEURISTIC
    calibrated: Literal[False] = False
    ranking: list[SourceScore] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
