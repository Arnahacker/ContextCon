"""Interfaces between layers. Each layer codes against these, never against
another layer's internals.

    read      : text            -> Form, FieldReading      (only layer that calls an LLM)
    evidence  : Form            -> EvidenceResult          (only layer that calls Crustdata / web)
    decide    : DecideInput     -> Decision                (pure: no network, no LLM, no clock)
    case      : orchestrates the three, persists every step, resumes after a crash
    api       : HTTP + the one-page UI
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from invariant.shapes import Fact

# ------------------------------------------------------------- canonical fields
# Fact.field must be one of these. Tier 0/1 block pricing; Tier 2 never blocks.

TIER0 = ["company"]
TIER1 = ["occupancy", "headcount", "sites", "cover_type", "sum_insured"]
TIER2 = ["claims_history", "construction", "fire_protection", "export_countries", "turnover", "wages"]
# components used by fallback ladders
COMPONENTS = [
    "building_owned", "building_area_sqft", "roof_type", "building_value",
    "machinery_value", "monthly_sales", "stock_weeks", "stock_value",
    "pf_monthly", "adverse_event", "hazardous_activity", "sanctions",
]
ALL_FIELDS = TIER0 + TIER1 + TIER2 + COMPONENTS


class _M(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# ------------------------------------------------------------- read layer


class FieldReading(_M):
    """Result of reading one follow-up reply into one field."""

    field: str
    kind: Literal["value", "unknown", "refused"]
    value: Optional[object] = None
    low: Optional[float] = None  # when the reply gives a range ("15-20 thousand")
    high: Optional[float] = None
    display: str  # echo-back text: "I read that as Rs 4,50,00,000"


# ------------------------------------------------------------- evidence layer


class Candidate(_M):
    company_id: str
    name: str
    domain: Optional[str] = None
    location: Optional[str] = None
    confidence: float


class Resolution(_M):
    status: Literal["resolved", "ambiguous", "not_found", "unavailable"]
    company_id: Optional[str] = None
    name: Optional[str] = None
    domain: Optional[str] = None
    candidates: list[Candidate] = Field(default_factory=list)


class CallRecord(_M):
    endpoint: str
    request_hash: str
    cached: bool
    credits: float
    ok: bool
    ms: int
    error: Optional[str] = None


class EvidenceResult(_M):
    resolution: Resolution
    facts: list[Fact] = Field(default_factory=list)
    # evidence sources that failed (timeout, 5xx). Non-empty => decide must hold,
    # because silence is not "nothing bad found".
    unavailable: list[str] = Field(default_factory=list)
    calls: list[CallRecord] = Field(default_factory=list)


# ------------------------------------------------------------- decide layer


class DecideInput(_M):
    resolution: Resolution
    facts: list[Fact]  # declared + evidence + follow-up answers, all sourced
    unavailable: list[str] = Field(default_factory=list)
    questions_asked: int = 0
    injection_attempt: bool = False  # log-only, never changes the outcome
