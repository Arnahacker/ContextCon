"""The three frozen shapes. Nobody changes this file after 13:15 without telling everyone."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

# ---------------------------------------------------------------- the form
# The ONLY thing the Read step may output. Every field nullable.
# null means "they did not say", which is itself a finding.

FORM_FIELDS = [
    "company_name", "trade_names", "industry", "declared_headcount",
    "declared_sites", "countries", "activities", "cover_type",
    "sum_insured_inr", "ask",
    # added 22 Nov: identify by website, check a GSTIN, price WC and marine
    "domain", "gstin", "annual_wages_inr", "annual_shipments_inr",
]


@dataclass
class Form:
    company_name: Optional[str] = None
    trade_names: list[str] = field(default_factory=list)
    industry: Optional[str] = None
    declared_headcount: Optional[int] = None
    declared_sites: Optional[int] = None
    countries: list[str] = field(default_factory=list)
    activities: list[str] = field(default_factory=list)
    cover_type: Optional[str] = None
    sum_insured_inr: Optional[int] = None
    ask: Optional[str] = None
    domain: Optional[str] = None
    gstin: Optional[str] = None
    annual_wages_inr: Optional[int] = None
    annual_shipments_inr: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Form":
        """Tolerant: ignores unknown keys, fills missing ones with defaults."""
        clean = {k: d[k] for k in FORM_FIELDS if k in d and d[k] is not None}
        return Form(**clean)


# JSON schema handed to the model. Keep it strict: no extra keys, no prose.
FORM_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "company_name":       {"type": ["string", "null"]},
        "trade_names":        {"type": "array", "items": {"type": "string"}},
        "industry":           {"type": ["string", "null"]},
        "declared_headcount": {"type": ["integer", "null"]},
        "declared_sites":     {"type": ["integer", "null"]},
        "countries":          {"type": "array", "items": {"type": "string"}},
        "activities":         {"type": "array", "items": {"type": "string"}},
        "cover_type":         {"type": ["string", "null"],
                               "description": "fire, burglary, marine_cargo or wc "
                                              "(workmen's compensation), only if stated"},
        "sum_insured_inr":    {"type": ["integer", "null"]},
        "ask":                {"type": ["string", "null"]},
        "domain":             {"type": ["string", "null"],
                               "description": "the company's website, if given"},
        "gstin":              {"type": ["string", "null"],
                               "description": "a 15-character GST number, if given"},
        "annual_wages_inr":   {"type": ["integer", "null"]},
        "annual_shipments_inr": {"type": ["integer", "null"]},
    },
    "required": FORM_FIELDS,
}

# ---------------------------------------------------------------- outcomes
QUOTE, REFER, DECLINE, HOLD = "quote", "refer", "decline", "hold"
OUTCOMES = (QUOTE, REFER, DECLINE, HOLD)


@dataclass
class Question:
    field: str
    ask: str
    worth_inr: int
    record_we_need: str

    def to_dict(self): return asdict(self)


@dataclass
class Step:
    rule: str
    multiplier: float
    because: list[str]
    explain: str = ""

    def to_dict(self): return asdict(self)


@dataclass
class Decision:
    outcome: str
    premium_inr: int = 0
    hold_reason: Optional[str] = None
    gate: dict[str, Any] = field(default_factory=lambda: {"blocked": False, "missing": []})
    steps: list[Step] = field(default_factory=list)
    questions: list[Question] = field(default_factory=list)
    would_flip_if: list[dict[str, Any]] = field(default_factory=list)
    hash: str = ""
    rules_version: str = ""
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d
