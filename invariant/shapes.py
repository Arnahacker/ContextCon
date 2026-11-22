"""The three frozen shapes every layer shares: Form, Fact, Decision.

Change these only with agreement from every layer owner. Rules enforced here:
- A Fact that is not `cannot_verify` cannot exist without a Source.
- A `derived` Fact cannot exist without its Derivation (formula + inputs + range).
- The Form is the ONLY thing the Read layer may output.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

# ---------------------------------------------------------------- vocabularies

Origin = Literal["declared", "applicant_followup", "crustdata", "web", "registry", "derived"]
EvidenceKind = Literal["direct", "lower_bound", "proxy_range", "claim"]
Status = Literal["matches", "contradicts", "consistent_unconfirmed", "cannot_verify", "undeclared"]
CompanyMatch = Literal["company_id", "domain", "name_city", "not_applicable"]
Outcome = Literal["quote", "refer", "decline", "hold"]
HoldReason = Literal["ambiguous_company", "company_not_found", "evidence_unavailable", "awaiting_answers"]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# ---------------------------------------------------------------- 1. the form


class Form(_Frozen):
    """What the LLM fills from the broker's text. Every field may be null:
    null means the applicant did not say, which is itself a finding."""

    company_name: Optional[str] = None
    trade_names: list[str] = Field(default_factory=list)
    domain: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    industry: Optional[str] = None
    declared_headcount: Optional[int] = None
    declared_sites: Optional[int] = None
    countries: list[str] = Field(default_factory=list)
    activities: list[str] = Field(default_factory=list)
    cover_type: Optional[str] = None
    sum_insured_inr: Optional[int] = None
    ask: Optional[str] = None
    # Log-only: set when the text contains instructions aimed at the system.
    # Never read by the Decide layer and never part of the hash.
    injection_attempt: bool = False


# ---------------------------------------------------------------- 2. a fact


class Source(_Frozen):
    what: str  # e.g. "POST /company/enrich -> headcount.total"
    url: Optional[str] = None
    dated: Optional[str] = None  # when the record itself is from (None = unknown)
    fetched: str  # ISO timestamp we fetched it; excluded from the hash
    quote: str  # the exact snippet / field value we relied on


class Derivation(_Frozen):
    formula: str  # e.g. "area_sqft * cost_per_sqft"
    inputs: list[str]  # fact ids
    range: tuple[float, float]


class Fact(_Frozen):
    id: str
    field: str
    value: Any = None
    origin: Origin
    evidence_kind: EvidenceKind
    status: Status
    company_match: CompanyMatch = "not_applicable"
    source: Optional[Source] = None
    derivation: Optional[Derivation] = None

    @model_validator(mode="after")
    def _no_fact_without_source(self) -> "Fact":
        if self.status != "cannot_verify" and self.source is None:
            raise ValueError(f"fact {self.id!r}: status {self.status!r} requires a source")
        if self.origin == "derived" and self.derivation is None:
            raise ValueError(f"fact {self.id!r}: derived facts require a derivation")
        if self.origin in ("crustdata", "web", "registry") and self.company_match == "not_applicable":
            raise ValueError(f"fact {self.id!r}: evidence facts must say how they match the company")
        return self


# ---------------------------------------------------------------- 3. the decision


class Step(_Frozen):
    rule: str  # e.g. "HEADCOUNT_UNDERSTATED"
    multiplier: float
    because: list[str]  # fact ids


class Question(_Frozen):
    field: str
    ask: str
    worth_inr: int
    record_we_need: str
    rung: int = 1
    options: list[str] = Field(default_factory=list)  # for multiple choice rungs


class Flip(_Frozen):
    fact: str
    change: str  # human readable, e.g. "below 150"
    then: Outcome


class Gate(_Frozen):
    blocked: bool
    missing: list[str] = Field(default_factory=list)


class Decision(_Frozen):
    outcome: Outcome
    hold_reason: Optional[HoldReason] = None
    candidates: list[dict] = Field(default_factory=list)  # for ambiguous_company
    gate: Gate
    premium_inr: Optional[int] = None
    premium_range_inr: Optional[tuple[int, int]] = None
    steps: list[Step] = Field(default_factory=list)
    questions: list[Question] = Field(default_factory=list)
    would_flip_if: list[Flip] = Field(default_factory=list)
    findings: list[str] = Field(default_factory=list)  # log-only notes, e.g. injection attempt
    hash: str
    rules_version: str
