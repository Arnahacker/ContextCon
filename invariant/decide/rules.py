"""Underwriting rules: facts -> named Steps. Pure (dates are compared as strings
of the facts themselves; there is no clock)."""
from __future__ import annotations

from typing import Optional

from invariant.shapes import Fact, Step

from .rate_card import LOADINGS
from .values import facts_for

DECLINE_RULES = {"CONFIRMED_FIRE", "SANCTIONS_MATCH"}
REFER_RULES = {"HEADCOUNT_UNDERSTATED", "UNDECLARED_SITE", "UNDECLARED_HAZARD", "ADVERSE_EVENT"}
SEVERE_EVENTS = {"fire", "explosion"}
RECENT_MONTHS = 24


def months(date: Optional[str]) -> Optional[int]:
    """'2026-10-14' -> months since year 0. None if not a date."""
    if not isinstance(date, str) or len(date) < 7 or date[4] != "-":
        return None
    try:
        return int(date[:4]) * 12 + int(date[5:7]) - 1
    except ValueError:
        return None


def _event_date(f: Fact) -> Optional[str]:
    v = f.value if isinstance(f.value, dict) else {}
    return v.get("date") or (f.source.dated if f.source else None)


def reference_month(facts: list[Fact]) -> Optional[int]:
    """Most recent date carried by any fact (source.dated or an event date)."""
    ms = [m for f in facts for m in (months(f.source.dated if f.source else None),
                                     months(_event_date(f) if f.field == "adverse_event" else None)) if m]
    return max(ms) if ms else None


def is_recent_severe(f: Fact, ref: Optional[int]) -> bool:
    v = f.value if isinstance(f.value, dict) else {}
    m = months(_event_date(f))
    return v.get("type") in SEVERE_EVENTS and m is not None and ref is not None and ref - m <= RECENT_MONTHS


def _ids(facts: list[Fact]) -> list[str]:
    return sorted(f.id for f in facts)


def evaluate(facts: list[Fact], derived_tier1: dict[str, list[str]], skipped: list[str]) -> list[Step]:
    steps: list[Step] = []

    hc = facts_for(facts, "headcount")
    contra = [f for f in hc if f.status == "contradicts"]
    if contra:
        claims = [f for f in hc if f.origin in ("declared", "applicant_followup")]
        steps.append(Step(rule="HEADCOUNT_UNDERSTATED", multiplier=LOADINGS["HEADCOUNT_UNDERSTATED"],
                          because=_ids(claims) + _ids(contra)))

    for f in facts_for(facts, "sites"):
        if f.status == "undeclared":
            steps.append(Step(rule="UNDECLARED_SITE", multiplier=LOADINGS["UNDECLARED_SITE"], because=[f.id]))

    hazards = [f for f in facts_for(facts, "hazardous_activity") if f.status == "undeclared"]
    if hazards:
        steps.append(Step(rule="UNDECLARED_HAZARD", multiplier=LOADINGS["UNDECLARED_HAZARD"], because=_ids(hazards)))

    ref = reference_month(facts)
    events = [f for f in facts_for(facts, "adverse_event") if f.status in ("undeclared", "contradicts")]
    severe = [f for f in events if is_recent_severe(f, ref)]
    other = [f for f in events if f not in severe]
    if severe:
        steps.append(Step(rule="CONFIRMED_FIRE", multiplier=1.0, because=_ids(severe)))
    if other:
        steps.append(Step(rule="ADVERSE_EVENT", multiplier=LOADINGS["ADVERSE_EVENT"], because=_ids(other)))

    hits = [f for f in facts_for(facts, "sanctions")
            if f.status == "contradicts" and isinstance(f.value, dict) and f.value.get("match")]
    if hits:
        steps.append(Step(rule="SANCTIONS_MATCH", multiplier=1.0, because=_ids(hits)))

    claims_facts = facts_for(facts, "claims_history")
    if claims_facts and all(f.status == "cannot_verify" or f.value is None for f in claims_facts):
        steps.append(Step(rule="CLAIMS_HISTORY_UNKNOWN", multiplier=LOADINGS["CLAIMS_HISTORY_UNKNOWN"],
                          because=_ids(claims_facts)))

    for field in sorted(derived_tier1):
        steps.append(Step(rule="DERIVED_VALUE", multiplier=LOADINGS["DERIVED_VALUE"], because=derived_tier1[field]))

    for field in sorted(skipped):
        if field == "claims_history":
            continue  # has its own named rule
        steps.append(Step(rule=f"UNKNOWN_{field.upper()}", multiplier=LOADINGS["UNKNOWN"],
                          because=_ids(facts_for(facts, field))))
    return steps


def outcome(steps: list[Step]) -> str:
    rules = {s.rule for s in steps}
    if rules & DECLINE_RULES:
        return "decline"
    if rules & REFER_RULES:
        return "refer"
    return "quote"


def multiplier(steps: list[Step]) -> float:
    m = 1.0
    for s in steps:
        m *= s.multiplier
    return m
