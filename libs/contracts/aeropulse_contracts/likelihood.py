"""Source likelihood v2 (source_likelihood.v2): a ranked, uncalibrated heuristic.

Scores are in [0, 1] and deliberately do not sum to 1. No gold label set
exists, so a ranking with evidence is shown, never percentages.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class EvidenceItem(BaseModel):
    """One signal that contributed to a ranking, with where it came from."""

    model_config = {"extra": "forbid"}

    signal: str
    source_id: str
    value: float | None
    unit: str | None = None
    observed_at: datetime | None = None


class SourceScore(BaseModel):
    """Score for one source class taken from the region's hazard profiles."""

    model_config = {"extra": "forbid"}

    source_class: str
    score: float = Field(..., ge=0.0, le=1.0)
    contributing_signals: list[str] = Field(default_factory=list)


class SourceLikelihoodV2(BaseModel):
    """Ranked likely source classes for one cell and hour."""

    model_config = {"extra": "forbid"}

    schema_version: Literal["source_likelihood.v2"] = "source_likelihood.v2"
    region_id: str
    grid_id: str
    valid_at: datetime
    method_version: str
    provenance_class: Literal["heuristic"] = "heuristic"
    calibrated: Literal[False] = False
    ranking: list[SourceScore]
    evidence: list[EvidenceItem] = Field(default_factory=list)
