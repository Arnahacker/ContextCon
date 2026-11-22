"""What would change my mind: re-run the assessment with each driving fact neutralised. Pure."""
from __future__ import annotations

import math
from typing import Callable, Optional

from invariant.shapes import Fact, Flip, Step

from .rules import DECLINE_RULES, REFER_RULES
from .values import declared_headcount

HEADCOUNT_TOLERANCE = 1.25


def _drivers(steps: list[Step], facts: list[Fact]) -> list[Fact]:
    by_id = {f.id: f for f in facts}
    out: list[Fact] = []
    for s in steps:
        if s.rule not in DECLINE_RULES | REFER_RULES:
            continue
        for fid in s.because:
            f = by_id.get(fid)
            # only evidence findings drive; the applicant's own claim is not "flippable"
            if f and f.status in ("contradicts", "undeclared") and f not in out:
                out.append(f)
    return out


def _neutralise(facts: list[Fact], f: Fact) -> tuple[list[Fact], str]:
    rest = [x for x in facts if x.id != f.id]
    v = f.value if isinstance(f.value, dict) else {}
    if f.field == "headcount":
        limit = math.floor((declared_headcount(facts) or 0) * HEADCOUNT_TOLERANCE)
        return rest + [f.model_copy(update={"value": limit, "status": "consistent_unconfirmed"})], \
            f"record headcount at or below {limit}"
    if f.field == "sites":
        return rest, f"no undeclared site at {f.value}"
    if f.field == "hazardous_activity":
        return rest, f"no {v.get('activity', 'hazardous activity')} at the insured"
    if f.field == "adverse_event":
        return rest, f"no confirmed {v.get('type', 'adverse event')}: {v.get('title', '')}".rstrip(": ")
    if f.field == "sanctions":
        return rest, "no sanctions match"
    return rest, f"without {f.id}"


def would_flip_if(facts: list[Fact], steps: list[Step], outcome: str,
                  assess_outcome: Callable[[list[Fact]], Optional[str]]) -> list[Flip]:
    """One Flip per driving fact whose neutralisation alone changes the outcome.

    When several independent findings each hold the outcome (none flips alone),
    report each driver with the outcome once all drivers are cleared, and say so."""
    drivers = _drivers(steps, facts)
    flips: list[Flip] = []
    for f in drivers:
        alt, change = _neutralise(facts, f)
        then = assess_outcome(alt)
        if then is not None and then != outcome:
            flips.append(Flip(fact=f.id, change=change, then=then))
    if flips or len(drivers) < 2:
        return flips
    all_clear = facts
    changes = {}
    for f in drivers:
        all_clear, changes[f.id] = _neutralise(all_clear, f)
    then = assess_outcome(all_clear)
    if then is None or then == outcome:
        return []
    n = len(drivers) - 1
    return [Flip(fact=f.id, change=f"{changes[f.id]} (with the other {n} finding{'s' if n > 1 else ''} also cleared)",
                 then=then) for f in drivers]
