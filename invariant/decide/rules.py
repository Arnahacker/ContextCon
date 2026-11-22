"""Underwriting rules: facts -> named Steps. Pure (dates are compared as strings
of the facts themselves; there is no clock)."""
from __future__ import annotations

from typing import Optional

from invariant.shapes import Fact, Step

from .rate_card import FIRE_PER_MILLE, LOADINGS
from .values import facts_for

DECLINE_RULES = {"CONFIRMED_FIRE", "SANCTIONS_MATCH"}
REFER_RULES = {"HEADCOUNT_UNDERSTATED", "UNDECLARED_SITE", "UNDECLARED_HAZARD", "ADVERSE_EVENT",
               "UNDISCLOSED_ESSENTIAL", "OCCUPANCY_MISMATCH", "COVER_NOT_PRICED"}
UNPRICED_COVERS: set[str] = set()  # a recognised cover with no rate card would be verified, then referred
SEVERE_EVENTS = {"fire", "explosion"}
MAX_SITE_LOADINGS = 3  # undeclared sites beyond this are still shown and still refer, at x1.0
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


def confirmed(facts: list[Fact], field: str) -> Optional[bool]:
    """The applicant's answer when shown a record finding: True (the record is right / yes),
    False (no / my figure is right), None (not asked yet, or "don't know")."""
    fs = [f for f in facts_for(facts, field) if f.origin == "applicant_followup"]
    if not fs or fs[-1].status == "cannot_verify" or not isinstance(fs[-1].value, str):
        return None
    v = fs[-1].value.strip().lower()
    if v.startswith(("yes", "the record", "record", "haan")):
        return True
    if v.startswith(("no", "my figure", "mine", "nahi")):
        return False
    return None


def undeclared_sites(facts: list[Fact]) -> list[Fact]:
    """Record locations the applicant did not mention (a count is not a location)."""
    return [f for f in facts_for(facts, "sites") if f.status == "undeclared"
            and ((isinstance(f.value, dict) and f.value.get("city")) or isinstance(f.value, str))]


def undeclared_hazards(facts: list[Fact]) -> list[Fact]:
    return [f for f in facts_for(facts, "hazardous_activity") if f.status == "undeclared"]


def evaluate(facts: list[Fact], derived_tier1: dict[str, list[str]], skipped: list[str],
             undisclosed: tuple[str, ...] | list[str] = ()) -> list[Step]:
    steps: list[Step] = []

    hc = facts_for(facts, "headcount")
    contra = [f for f in hc if f.status == "contradicts"]
    if contra and confirmed(facts, "confirm_headcount") is not True:
        claims = [f for f in hc if f.origin in ("declared", "applicant_followup")]
        steps.append(Step(rule="HEADCOUNT_UNDERSTATED", multiplier=LOADINGS["HEADCOUNT_UNDERSTATED"],
                          because=_ids(claims) + _ids(contra)))

    occ = facts_for(facts, "occupancy")
    occ_contra = [f for f in occ if f.status == "contradicts" and isinstance(f.value, str)]
    if occ_contra:  # the record says a different trade: refer, priced at the dearer of the two rates
        claims = [f for f in occ if f.origin in ("declared", "applicant_followup") and isinstance(f.value, str)]
        said = claims[0].value if claims else "other"
        rate = lambda o: FIRE_PER_MILLE.get(o, FIRE_PER_MILLE["other"])  # noqa: E731
        ratio = max(rate(f.value) for f in occ_contra) / rate(said)
        steps.append(Step(rule="OCCUPANCY_MISMATCH", multiplier=round(max(1.0, ratio), 2),
                          because=_ids(claims) + _ids(occ_contra)))

    # every undeclared site is listed with its source, but only the first MAX_SITE_LOADINGS
    # load the price (a global firm with 16 offices must not compound 1.1^16 = x4.6)
    # once the applicant confirms the extra sites are theirs, they are disclosed: nothing to refer
    n_loaded = 0
    if confirmed(facts, "confirm_sites") is not True:
        for f in undeclared_sites(facts):
            mult = LOADINGS["UNDECLARED_SITE"] if n_loaded < MAX_SITE_LOADINGS else 1.0
            n_loaded += 1
            steps.append(Step(rule="UNDECLARED_SITE", multiplier=mult, because=[f.id]))

    hazards = undeclared_hazards(facts)
    if hazards:
        # disclosed when asked: still priced for the hazard, but no longer hidden (no referral)
        rule = "DISCLOSED_HAZARD" if confirmed(facts, "confirm_hazard") is True else "UNDECLARED_HAZARD"
        steps.append(Step(rule=rule, multiplier=LOADINGS["UNDECLARED_HAZARD"], because=_ids(hazards)))

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

    if undisclosed:  # essential information only the applicant holds was not given
        steps.append(Step(rule="UNDISCLOSED_ESSENTIAL", multiplier=LOADINGS["UNDISCLOSED_ESSENTIAL"],
                          because=sorted(undisclosed)))

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
