"""What would change my mind, and what each unanswered question is worth.

Both work by re-running decide() with one thing changed. This is only possible
because decide() is pure and cheap. Also no network, no model.
"""
from __future__ import annotations
import copy
from dataclasses import replace
from typing import Any

from .facts import Fact, Source, MATCHES, CONTRADICTS, CANNOT_VERIFY, UNDECLARED
from .decide import decide, resolved, by_field
from .assume import assume_for_pricing
from .schemas import Question

# a plausible "good news" answer for each askable field, used only to price
# the question. Never shown as a fact, never reaches a real decision.
HYPOTHETICAL = {
    "claims_history":  ("none in five years", MATCHES),
    "construction":    ("pucca", MATCHES),
    "protection":      ("hydrant", MATCHES),
    "sum_insured_inr": (10_000_000, MATCHES),
    "annual_wages_inr": (20_000_000, MATCHES),
    "annual_shipments_inr": (100_000_000, MATCHES),
    "cover_type":      ("fire", MATCHES),
    "occupancy":       ("light_manufacturing", MATCHES),
    "company_identity": ("crust:hypothetical", MATCHES),
}


def _hypothetical_fact(fld: str) -> Fact | None:
    if fld not in HYPOTHETICAL:
        return None
    val, status = HYPOTHETICAL[fld]
    return Fact(id=f"__what_if_{fld}", field=fld, value=val, origin="derived",
                status=status, evidence_kind="direct",
                source=Source(what="hypothetical answer, for pricing the question only"))


def _without(facts: list[Fact], fld: str) -> list[Fact]:
    return [f for f in facts if f.field != fld]


def price_questions(facts: list[Fact], rules: dict[str, Any]) -> list[Question]:
    """The shortest useful question list. Each one priced by what answering it saves.

    A question earns its place only if answering it changes the premium or
    unblocks the gate. Anything else is noise we do not put in front of a broker.
    """
    priced = assume_for_pricing(facts)   # so a blocked case still has a number to move
    now = decide(priced, rules)
    facts = priced
    # what THIS cover needs, then the rest; a question survives only if
    # answering it unblocks the gate or moves the premium
    askable = list(dict.fromkeys(rules["gate"]["tier0"] + now.gate["missing"] +
                                 rules["gate"]["tier1"] + rules["gate"]["tier2"]))
    out: list[Question] = []

    for fld in askable:
        has_real_answer = resolved(facts, fld)
        if has_real_answer:
            continue
        hyp = _hypothetical_fact(fld)
        if hyp is None:
            continue
        trial = _without(facts, fld) + [hyp]
        after = decide(trial, rules)

        unblocks = fld in now.gate["missing"]
        saving = max(0, now.premium_inr - after.premium_inr)
        changes_outcome = after.outcome != now.outcome

        if not (unblocks or saving > 0 or changes_outcome):
            continue
        out.append(Question(
            field=fld,
            ask=rules["question_text"].get(fld, f"What is the {fld}?"),
            worth_inr=int(saving),
            record_we_need=rules["records_we_need"].get(fld, "no public record"),
        ))

    # most valuable first; gate-blockers always on top because nothing prices without them
    out.sort(key=lambda q: (q.field not in now.gate["missing"], -q.worth_inr))
    return out


def _neutralise(f: Fact, facts: list[Fact]) -> tuple[str, list[Fact]] | None:
    """What this case would look like if this one fact were different."""
    rest = [x for x in facts if x.id != f.id]
    if f.status == CONTRADICTS:
        return (f"{f.field} confirmed as declared", rest)
    if f.status == UNDECLARED:
        return (f"the {f.field} finding were about another company", rest)
    if f.field == "adverse_event_severe":
        return ("the loss event were not this company", rest)
    if f.status == CANNOT_VERIFY:
        hyp = _hypothetical_fact(f.field)
        if hyp is not None:
            return (f"{f.field} were answered", rest + [hyp])
    return None


def would_change_my_mind(facts: list[Fact], rules: dict[str, Any],
                         limit: int = 4, material_pct: float = 5.0
                         ) -> list[dict[str, Any]]:
    """The facts that would flip the outcome, or move the premium materially.

    Tries one fact at a time first. If nothing alone flips the outcome, it
    tries pairs, so the answer is "these two together" rather than silence.
    Every branch is just another decide() call.
    """
    facts = assume_for_pricing(facts)
    now = decide(facts, rules)
    cands = [f for f in facts if _neutralise(f, facts) is not None]
    out: list[dict[str, Any]] = []

    def record(label, after, ids):
        delta = now.premium_inr - after.premium_inr
        out.append({
            "facts": ids,
            "if": label,
            "then": after.outcome,
            "flips_outcome": after.outcome != now.outcome,
            "premium_now_inr": now.premium_inr,
            "premium_then_inr": after.premium_inr,
            "saves_inr": max(0, delta),
        })

    for f in cands:
        label, trial = _neutralise(f, facts)
        after = decide(trial, rules)
        moved = now.premium_inr and \
            abs(now.premium_inr - after.premium_inr) / now.premium_inr * 100 >= material_pct
        if after.outcome != now.outcome or moved:
            record(label, after, [f.id])

    # nothing alone flips it? say which pair does.
    if not any(r["flips_outcome"] for r in out):
        for i in range(len(cands)):
            for j in range(i + 1, len(cands)):
                a, b = cands[i], cands[j]
                la, _ = _neutralise(a, facts)
                lb, _ = _neutralise(b, facts)
                drop = {a.id, b.id}
                trial = [x for x in facts if x.id not in drop]
                for f in (a, b):
                    if f.status == CANNOT_VERIFY:
                        h = _hypothetical_fact(f.field)
                        if h is not None:
                            trial.append(h)
                after = decide(trial, rules)
                if after.outcome != now.outcome:
                    record(f"{la} AND {lb}", after, [a.id, b.id])
                    break
            if any(r["flips_outcome"] for r in out):
                break

    out.sort(key=lambda r: (not r["flips_outcome"], -r["saves_inr"]))
    return out[:limit]
