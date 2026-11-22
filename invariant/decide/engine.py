"""decide(): same facts in, same decision out.

Pure: no network, no LLM, no clock, no randomness. injection_attempt and
questions_asked never touch the hash or the outcome."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from invariant.contracts import TIER1, DecideInput
from invariant.shapes import Decision, Fact, Gate, Question, Source, Step

from . import counterfactual, derive as derive_mod, gate, ladders, norms, rate_card, rules
from .hashing import decision_hash
from .values import Range, fact_range, headcount, is_range, mid, occupancy, pick

RULES_VERSION = "2026.11.22.2"
MIN_QUESTION_WORTH = 5_000
MAX_QUESTIONS = 5
# A loading the applicant could remove with one yes/no is always offered, even when cheap.
ALWAYS_OFFER = {"claims_history"}


# ---------------------------------------------------------------- assessment


@dataclass(frozen=True)
class Assessment:
    facts: list[Fact]  # input + derived
    steps: list[Step]
    missing: list[str]
    outcome: Optional[str]  # None while the gate is blocked
    premium: Optional[tuple[int, int, int]]  # (low, mid, high) incl. GST
    wages: Optional[tuple[float, float, float]]
    cover: Optional[str]


def _triple(r: Range) -> tuple[float, float, float]:
    return (r[0], mid(r), r[1])


def _wages(facts: list[Fact]) -> Optional[tuple[float, float, float]]:
    r = fact_range(pick(facts, "wages"))
    if r:
        return _triple(r)
    hc = headcount(facts)
    if hc is None:
        return None
    lo, md, hi = norms.MONTHLY_WAGE
    return (hc * 12 * lo, hc * 12 * md, hc * 12 * hi)  # estimate: headcount x 12 x monthly wage


def assess(raw: list[Fact]) -> Assessment:
    raw = [f for f in raw if f.origin != "derived"]
    facts = raw + derive_mod.derive(raw)
    missing = gate.missing(facts)
    cover_f = pick(facts, "cover_type")
    cover = cover_f.value if cover_f else None

    derived_tier1: dict[str, list[str]] = {}
    for field in TIER1:
        f = pick(facts, field)
        if f and (f.origin == "derived" or is_range(f.value)):
            derived_tier1[field] = [f.id]
    skipped = ladders.skipped_fields(facts)
    if cover not in ("wc", "fire_wc"):
        skipped = [s for s in skipped if s != "wages"]
    steps = rules.evaluate(facts, derived_tier1, skipped)

    if missing:
        return Assessment(facts, steps, missing, None, None, None, cover)
    si = fact_range(pick(facts, "sum_insured"))
    wages = _wages(facts) if cover in ("wc", "fire_wc") else None
    premium = rate_card.price(cover, occupancy(facts) or "other", _triple(si) if si else None, wages,
                              rules.multiplier(steps))
    return Assessment(facts, steps, [], rules.outcome(steps), premium, wages, cover)


# ---------------------------------------------------------------- questions


def _hypothetical(field: str, value) -> Fact:
    return Fact(id=f"followup_{field}_hypothetical", field=field, value=value, origin="applicant_followup",
                evidence_kind="claim", status="consistent_unconfirmed",
                source=Source(what="hypothetical answer", fetched="", quote=f"{field}: {value}"))


def _pins(field: str, a: Assessment) -> list:
    """Hypothetical answers used to price what knowing the field is worth."""
    if field == "claims_history":
        return ["no"]
    spec = ladders.spec_for(field)
    if field == "building_owned":
        return [True, False]
    if spec and spec.options and field not in ("sum_insured", "occupancy", "cover_type"):
        return list(spec.options)
    if field == "wages" and a.wages:
        return [int(a.wages[1])]
    if field == "pf_monthly" and a.wages:
        return [int(a.wages[1] * norms.PF_RATE / 12)]
    if field == "stock_weeks":
        return [mid(norms.stock_weeks(occupancy(a.facts)))]
    f = pick(a.facts, field)
    if f and f.derivation:
        return [int(mid(f.derivation.range))]
    return []


def worth(raw: list[Fact], a: Assessment, field: str) -> int:
    """Half the premium spread the answer removes + the loading it removes (by re-pricing)."""
    if a.premium is None:
        return 0
    pins = _pins(field, a)
    alts = [assess(raw + [_hypothetical(field, v)]).premium for v in pins]
    alts = [p for p in alts if p]
    if not alts:
        return 0
    if len(alts) > 1:  # multiple choice: the spread across the options
        mids = [p[1] for p in alts]
        return int((max(mids) - min(mids)) / 2)
    p = alts[0]
    spread_now, spread_after = a.premium[2] - a.premium[0], p[2] - p[0]
    return int(max(0, spread_now - spread_after) / 2 + max(0, a.premium[1] - p[1]))


def questions(raw: list[Fact], a: Assessment) -> list[Question]:
    rule_names = {s.rule for s in a.steps}
    out: list[tuple[tuple, Question]] = []
    for order, field in enumerate(ladders.LADDERS):
        if field == "claims_history" and "CLAIMS_HISTORY_UNKNOWN" not in rule_names:
            continue
        if field == "wages" and a.cover not in ("wc", "fire_wc"):
            continue
        st = ladders.state(a.facts, field)
        blocking = field in a.missing
        for spec in st.pending:
            w = worth(raw, a, spec.field)
            if not blocking and w < MIN_QUESTION_WORTH and field not in ALWAYS_OFFER:
                continue
            q = Question(field=spec.field, ask=spec.ask, worth_inr=w, record_we_need=spec.record_we_need,
                         rung=st.rung, options=list(spec.options))
            out.append(((0 if blocking else 1, -w, order), q))
    return [q for _, q in sorted(out, key=lambda t: t[0])]


# ---------------------------------------------------------------- decide


def _findings(inp: DecideInput) -> list[str]:
    out = []
    if inp.injection_attempt:
        out.append("injection_attempt: instructions in the prompt were ignored")
    for src in sorted(inp.unavailable):
        out.append(f"evidence_unavailable: {src} did not answer; held for a human (silence is not 'nothing found')")
    return out


def _resolution_hold(inp: DecideInput, base: dict) -> Optional[Decision]:
    res = inp.resolution
    if res.status == "ambiguous":
        cands = [c.model_dump() for c in res.candidates]
        names = " or ".join(f"{c.name} ({c.location or c.domain or c.company_id})" for c in res.candidates)
        q = Question(field="company", ask=f"Which company do you mean: {names}?", worth_inr=0,
                     record_we_need="the applicant's website or registered city", rung=0,
                     options=[f"{c.name} ({c.location or c.domain or c.company_id})" for c in res.candidates])
        return Decision(outcome="hold", hold_reason="ambiguous_company", candidates=cands,
                        gate=Gate(blocked=True, missing=["company"]), questions=[q], **base)
    if res.status == "not_found":
        q = Question(field="company", ask="We could not find this company. What is its website or city?",
                     worth_inr=0, record_we_need="the applicant's website or registered city", rung=0)
        return Decision(outcome="hold", hold_reason="company_not_found",
                        gate=Gate(blocked=True, missing=["company"]), questions=[q], **base)
    if res.status == "unavailable":
        return Decision(outcome="hold", hold_reason="evidence_unavailable",
                        gate=Gate(blocked=True, missing=["company"]), **base)
    return None


def decide(inp: DecideInput) -> Decision:
    raw = list(inp.facts)
    a = assess(raw)
    base = dict(hash=decision_hash(inp.resolution.company_id, a.facts, RULES_VERSION),
                rules_version=RULES_VERSION, findings=_findings(inp))

    if hold := _resolution_hold(inp, base):
        return hold
    if inp.unavailable:
        return Decision(outcome="hold", hold_reason="evidence_unavailable", steps=a.steps,
                        gate=Gate(blocked=bool(a.missing), missing=a.missing), **base)

    qs = [] if inp.questions_asked >= MAX_QUESTIONS else questions(raw, a)
    if a.missing:
        return Decision(outcome="hold", hold_reason="awaiting_answers", gate=Gate(blocked=True, missing=a.missing),
                        steps=a.steps, questions=qs, **base)

    flips = counterfactual.would_flip_if(a.facts, a.steps, a.outcome, lambda fs: assess(fs).outcome)
    priced = a.outcome != "decline"
    return Decision(outcome=a.outcome, gate=Gate(blocked=False), steps=a.steps, questions=qs if priced else [],
                    premium_inr=a.premium[1] if priced else None,
                    premium_range_inr=(a.premium[0], a.premium[2]) if priced else None,
                    would_flip_if=flips, **base)
