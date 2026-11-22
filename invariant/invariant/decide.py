"""decide(facts, rules) -> Decision.

A PURE FUNCTION. No network, no model, no clock, no randomness, no file reads
beyond the rules passed in. Same facts in, same decision and same hash out.
That property is the whole product: do not import anything with side effects
into this file.
"""
from __future__ import annotations
import hashlib, json, math
from typing import Any, Optional, Iterable

from .facts import (Fact, MATCHES, CONTRADICTS, CONSISTENT_UNCONFIRMED,
                    CANNOT_VERIFY, UNDECLARED)
from .schemas import Decision, Step, Question, QUOTE, REFER, DECLINE, HOLD

RAPID_GROWTH_PCT = 100.0   # headcount more than doubled in the window


# ----------------------------------------------------------------- helpers
def by_field(facts: Iterable[Fact], fld: str) -> list[Fact]:
    return [f for f in facts if f.field == fld]


def first(facts: Iterable[Fact], fld: str) -> Optional[Fact]:
    hits = by_field(facts, fld)
    return hits[0] if hits else None


def resolved(facts: Iterable[Fact], fld: str) -> bool:
    """A field counts as resolved when real evidence or the applicant gives it a value.

    A DERIVED value never counts. Our own estimate can produce a provisional
    premium, but it can never clear the gate and it can never cause a decline.
    """
    for f in by_field(facts, fld):
        if f.origin == "derived":
            continue
        if f.value is not None and f.status in (MATCHES, CONTRADICTS,
                                                CONSISTENT_UNCONFIRMED, UNDECLARED):
            return True
    return False


def value_of(facts: Iterable[Fact], fld: str, default=None):
    for f in by_field(facts, fld):
        if f.value is not None:
            return f.value
    return default


def decision_hash(facts: Iterable[Fact], company_id: Optional[str],
                  rules_version: str) -> str:
    """Over the resolved company, the facts and the rules version.
    Never over the wording, the conversation, or the order answers arrived in."""
    keys = sorted(repr(f.hash_key()) for f in facts)
    blob = json.dumps({"company": company_id or "", "facts": keys,
                       "rules": rules_version}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


# ----------------------------------------------------------------- premium
def _exposure_premium(facts, rules) -> tuple[float, list[Step], list[str]]:
    """Base premium before modifiers. Returns (amount, steps, notes)."""
    steps: list[Step] = []
    notes: list[str] = []
    cover = value_of(facts, "cover_type", "fire")

    if cover == "wc":
        wages = value_of(facts, "annual_wages_inr")
        if wages is None:
            return 0.0, steps, ["wages not established"]
        cat = value_of(facts, "wc_category", "unknown")
        rate = rules["wc_rate_per_100_wages"].get(cat, rules["wc_rate_per_100_wages"]["unknown"])
        base = (wages / 100.0) * rate
        steps.append(Step(rule=f"WC_BASE_{cat.upper()}", multiplier=rate,
                          because=[f.id for f in by_field(facts, "annual_wages_inr")],
                          explain=f"wages {wages:,.0f} / 100 x {rate} per 100"))
        return base, steps, notes

    si = value_of(facts, "sum_insured_inr")
    if si is None:
        return 0.0, steps, ["sum insured not established"]
    occ = value_of(facts, "occupancy", "unknown")
    table = rules["occupancy_rate_per_mille"]
    rate = table.get(occ, table["unknown"])
    base = (si / 1000.0) * rate
    steps.append(Step(rule=f"FIRE_BASE_{occ.upper()}", multiplier=rate,
                      because=[f.id for f in by_field(facts, "occupancy")] or ["occupancy_default"],
                      explain=f"sum insured {si:,.0f} / 1000 x {rate} per mille"))
    return base, steps, notes


def _modifiers(facts, rules) -> list[Step]:
    """Named multipliers, each tied to the facts that triggered it."""
    out: list[Step] = []
    L, D = rules["loadings"], rules["discounts"]

    def load(name: str, because: list[str]):
        spec = L[name]
        out.append(Step(rule=name, multiplier=spec["multiplier"],
                        because=because, explain=spec["explain"]))

    def give(name: str, because: list[str]):
        spec = D[name]
        out.append(Step(rule=name, multiplier=spec["multiplier"],
                        because=because, explain=spec["explain"]))

    ident = first(facts, "company_identity")
    if ident is None or ident.status == CANNOT_VERIFY or ident.value is None:
        load("IDENTITY_UNVERIFIED", [ident.id] if ident else [])

    hc = [f for f in by_field(facts, "headcount") if f.status == CONTRADICTS]
    if hc:
        load("HEADCOUNT_UNDERSTATED", [f.id for f in by_field(facts, "headcount")])

    haz = [f for f in by_field(facts, "undeclared_hazard") if f.status == UNDECLARED]
    if haz:
        load("UNDECLARED_HAZARD", [f.id for f in haz])

    site = [f for f in by_field(facts, "undeclared_site") if f.status == UNDECLARED]
    if site:
        load("UNDECLARED_SITE", [f.id for f in site])

    adverse = [f for f in by_field(facts, "adverse_event") if f.status == MATCHES]
    if adverse:
        load("ADVERSE_EVENT_CONFIRMED", [f.id for f in adverse])

    safety = first(facts, "safety_function")
    if safety is not None and safety.value in (None, 0, "absent", False):
        load("NO_SAFETY_FUNCTION", [safety.id])

    growth = first(facts, "headcount_growth_pct")
    if growth is not None and isinstance(growth.value, (int, float)) and growth.value >= RAPID_GROWTH_PCT:
        load("RAPID_GROWTH", [growth.id])

    for fld, rule in (("claims_history", "CLAIMS_HISTORY_UNKNOWN"),
                      ("construction", "CONSTRUCTION_UNKNOWN"),
                      ("protection", "PROTECTION_UNKNOWN")):
        f = first(facts, fld)
        if f is None or f.status == CANNOT_VERIFY:
            load(rule, [f.id] if f else [])

    for cert in by_field(facts, "certification"):
        if cert.status == MATCHES and cert.value in D:
            give(cert.value, [cert.id])

    return out


def _apply(base: float, steps: list[Step], rules) -> int:
    total = base
    for s in steps:
        if s.rule.startswith(("FIRE_BASE", "WC_BASE")):
            continue
        total *= s.multiplier
    total = max(total, rules["minimum_premium_inr"]) if base > 0 else 0.0
    total *= (1 + rules["gst_rate"])
    return int(round(total))


# ----------------------------------------------------------------- the call
def decide(facts: list[Fact], rules: dict[str, Any]) -> Decision:
    ver = rules["version"]
    ident = first(facts, "company_identity")
    company_id = ident.value if ident else None
    h = decision_hash(facts, company_id, ver)

    def D(**kw) -> Decision:
        kw.setdefault("hash", h)
        kw.setdefault("rules_version", ver)
        return Decision(**kw)

    # 1. a source we needed did not answer. Silence is not "nothing bad found".
    if any(f.field == "evidence_unavailable" for f in facts):
        which = [f.value for f in by_field(facts, "evidence_unavailable")]
        return D(outcome=HOLD, hold_reason="evidence_unavailable",
                 notes=[f"could not reach: {', '.join(map(str, which))}"])

    # 2. two companies could match. Never guess.
    if ident is not None and ident.status == CONTRADICTS:
        cands = ident.note or "several candidates"
        return D(outcome=HOLD, hold_reason="ambiguous_company",
                 notes=[f"which company? {cands}"])

    # 3. hard stops
    for rule in rules.get("decline_rules", []):
        f = first(facts, rule["when_field"])
        if f is not None and f.origin != "derived" and f.status == MATCHES and f.value:
            return D(outcome=DECLINE,
                     steps=[Step(rule=rule["id"], multiplier=0.0,
                                 because=[f.id], explain=rule["explain"])],
                     notes=[rule["explain"]])

    # 4. the intake gate
    missing = [fld for fld in rules["gate"]["tier0"] + rules["gate"]["tier1"]
               if not resolved(facts, fld)]
    blocked = bool(missing)

    # 5. price it
    base, steps, notes = _exposure_premium(facts, rules)
    steps = steps + _modifiers(facts, rules)
    premium = _apply(base, steps, rules)

    # 6. quote, or refer
    needs_eyes = any(f.status in (CONTRADICTS, UNDECLARED) for f in facts) or \
                 any(s.rule in ("IDENTITY_UNVERIFIED", "ADVERSE_EVENT_CONFIRMED") for s in steps)
    if blocked:
        outcome = REFER
        notes.append(f"need {len(missing)} answer(s) before this can be priced")
    elif needs_eyes:
        outcome = REFER
    else:
        outcome = QUOTE

    return D(outcome=outcome, premium_inr=premium,
             gate={"blocked": blocked, "missing": missing},
             steps=steps, notes=notes)
