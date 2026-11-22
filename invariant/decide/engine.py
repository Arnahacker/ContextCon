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

RULES_VERSION = "2026.11.22.5"
MIN_QUESTION_WORTH = 5_000
MAX_QUESTIONS = 5  # caps optional questions only; a question that blocks pricing is always asked
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


BASE_REQUIRED = ["occupancy", "headcount", "sites", "cover_type"]
# what each line needs before it can be priced (fire / WC need the sum insured)
REQUIRED = {"marine": BASE_REQUIRED + ["cargo_value", "marine_route"],
            "liability": BASE_REQUIRED + ["liability_limit", "turnover"]}
LINE_FIELDS = {"cargo_value": "marine", "marine_route": "marine", "liability_limit": "liability", "turnover": "liability"}


def required(cover: Optional[str]) -> list[str]:
    return REQUIRED.get(cover or "", TIER1)


def assess(raw: list[Fact]) -> Assessment:
    raw = [f for f in raw if f.origin != "derived"]
    facts = raw + derive_mod.derive(raw)
    cover_f = pick(facts, "cover_type")
    cover = cover_f.value if cover_f else None
    need = required(cover)
    missing = gate.missing(facts, need)
    if cover == "liability" and "turnover" not in missing and derive_mod.usable_turnover(facts) is None:
        missing.append("turnover")  # a record band like $1B-$1T is not a turnover we can price on

    derived_tier1: dict[str, list[str]] = {}
    for field in need:
        f = pick(facts, field)
        if f and (f.origin == "derived" or is_range(f.value)):
            derived_tier1[field] = [f.id]
    skipped = ladders.skipped_fields(facts)
    if cover not in ("wc", "fire_wc"):
        skipped = [s for s in skipped if s != "wages"]
    steps = rules.evaluate(facts, derived_tier1, skipped, [f.id for f in derive_mod.undisclosed(raw)])

    if cover in rules.UNPRICED_COVERS:
        # no rate card for this line: everything is still verified, then a specialist prices it
        missing = [m for m in missing if m != "sum_insured"]
        steps = steps + [Step(rule="COVER_NOT_PRICED", multiplier=1.0, because=[cover_f.id])]
        return Assessment(facts, steps, missing, None if missing else rules.outcome(steps), None, None, cover)
    if missing:
        return Assessment(facts, steps, missing, None, None, None, cover)
    occ, mult = occupancy(facts) or "other", rules.multiplier(steps)
    if cover == "marine":
        route_f = pick(facts, "marine_route")
        premium = rate_card.price_marine(occ, _triple(fact_range(pick(facts, "cargo_value"))),
                                         str(route_f.value) if route_f else "international", mult)
        return Assessment(facts, steps, [], rules.outcome(steps), premium, None, cover)
    if cover == "liability":
        limit = mid(fact_range(pick(facts, "liability_limit")))
        premium = rate_card.price_liability(occ, limit, _triple(derive_mod.usable_turnover(facts)), mult)
        return Assessment(facts, steps, [], rules.outcome(steps), premium, None, cover)
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
    if field == "monthly_sales" and (est := derive_mod.monthly_sales_estimate(a.facts)):
        return [int(mid(est))]  # pinning the sales estimate removes its spread
    if field in _NUMERIC_OPTIONS:
        return _NUMERIC_OPTIONS[field]
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


# sample answers used only to test whether answering a question would unblock pricing
# options that the answer reader turns into amounts ("1 Cr" -> 10000000)
_NUMERIC_OPTIONS = {"liability_limit": [5_000_000, 10_000_000, 50_000_000, 100_000_000]}
_PROBES = {"building_area_sqft": [10_000], "monthly_sales": [1_000_000], "stock_weeks": [6],
           "machinery_value": [10_000_000], "sum_insured": [10_000_000], "headcount": [50], "sites": [1],
           "wages": [1_000_000], "pf_monthly": [10_000], "cargo_value": [10_000_000], "turnover": [100_000_000],
           **_NUMERIC_OPTIONS}


def _unblocks(raw: list[Fact], a: Assessment, spec: ladders.Spec) -> bool:
    """Would some answer to this question leave fewer Tier 1 fields missing?"""
    for v in (_PROBES.get(spec.field) or spec.options):
        if len(assess(raw + [_hypothetical(spec.field, v)]).missing) < len(a.missing):
            return True
    return False


def questions(raw: list[Fact], a: Assessment, optional: bool = True) -> list[Question]:
    """Blocking questions first (only those whose answer can unblock pricing), then optional
    priced questions worth at least MIN_QUESTION_WORTH (when `optional`)."""
    rule_names = {s.rule for s in a.steps}
    out: list[tuple[tuple, Question]] = []
    for order, field in enumerate(ladders.LADDERS):
        # claims history is always asked (no public record exists for private firms);
        # the loading applies only once the broker says they don't know.
        if field == "wages" and a.cover not in ("wc", "fire_wc"):
            continue
        if field in LINE_FIELDS and LINE_FIELDS[field] != a.cover and field not in a.missing:
            continue  # marine / liability questions only for that line
        if field == "sum_insured" and a.cover in REQUIRED:
            continue  # marine and liability are not priced on a sum insured
        st = ladders.state(a.facts, field)
        needed: set[str] = set()
        if field in a.missing:
            needed = {s.field for s in st.pending if _unblocks(raw, a, s)} or {s.field for s in st.pending}
        for spec in st.pending:
            blocking = spec.field in needed
            if not blocking and not optional:
                continue
            w = worth(raw, a, spec.field)
            if spec.field == "claims_history" and "CLAIMS_HISTORY_UNKNOWN" not in rule_names and a.premium:
                # not yet loaded: the question is worth the loading a "don't know" would add
                w = int(a.premium[1] * (rules.LOADINGS["CLAIMS_HISTORY_UNKNOWN"] - 1))
            if not blocking and w < MIN_QUESTION_WORTH and field not in ALWAYS_OFFER:
                continue
            q = Question(field=spec.field, ask=spec.ask, worth_inr=w, record_we_need=spec.record_we_need,
                         rung=st.rung, options=list(spec.options))
            out.append(((0 if blocking else 2, -w, order), q))
    for q in confirmations(raw, a):  # they can change the outcome, so never capped
        out.append(((1, -q.worth_inr, 0), q))
    return [q for _, q in sorted(out, key=lambda t: t[0])]


def _names(fs: list[Fact], key: str) -> str:
    vals = [str(f.value.get(key)) if isinstance(f.value, dict) else str(f.value) for f in fs
            if (isinstance(f.value, dict) and f.value.get(key)) or isinstance(f.value, str)]
    vals = list(dict.fromkeys(vals))
    return ", ".join(vals[:6]) + (f" and {len(vals) - 6} more" if len(vals) > 6 else "")


def confirmations(raw: list[Fact], a: Assessment) -> list[Question]:
    """Before holding a record finding against the applicant, show it to them and ask.
    Yes = disclosed (no referral); no / don't know = it stays a finding for a person."""
    def asked(field):
        return any(f.field == field and f.origin == "applicant_followup" for f in raw)

    def worth_of(field, value):
        if a.premium is None:
            return 0
        p = assess(raw + [_hypothetical(field, value)]).premium
        return max(0, a.premium[1] - p[1]) if p else 0

    out = []
    sites = rules.undeclared_sites(a.facts)
    if sites and not asked("confirm_sites"):
        out.append(Question(field="confirm_sites", rung=1, options=["yes", "no"], worth_inr=worth_of("confirm_sites", "yes"),
                            ask=f"Public records show the business also at {_names(sites, 'city')}. "
                                "Are these part of the business?",
                            record_we_need="GST registration (additional places of business)"))
    hazards = rules.undeclared_hazards(a.facts)
    if hazards and not asked("confirm_hazard"):
        out.append(Question(field="confirm_hazard", rung=1, options=["yes", "no"], worth_inr=worth_of("confirm_hazard", "yes"),
                            ask=f"Job ads show this work: {_names(hazards, 'activity')}. Does the business do it?",
                            record_we_need="factory licence or pollution board consent"))
    contra = [f for f in a.facts if f.field == "headcount" and f.status == "contradicts"]
    if contra and not asked("confirm_headcount"):
        said = [f for f in a.facts if f.field == "headcount" and f.origin in ("declared", "applicant_followup")
                and f.status != "cannot_verify"]
        out.append(Question(field="confirm_headcount", rung=1, options=["the record is right", "my figure is right"],
                            worth_inr=worth_of("confirm_headcount", "the record is right"),
                            ask=f"You said {said[0].value if said else 'fewer'} staff; public records show at least "
                                f"{contra[0].value}. Which is right?",
                            record_we_need="EPFO / ESIC returns"))
    return out


# ---------------------------------------------------------------- decide


def _findings(inp: DecideInput) -> list[str]:
    out = []
    if inp.injection_attempt:
        out.append("injection_attempt: instructions in the prompt were ignored")
    for src in sorted(inp.unavailable):
        out.append(f"evidence_unavailable: {src} did not answer; held for a human (silence is not 'nothing found')")
    if note := derive_mod.underinsurance(list(inp.facts)):
        out.append(note)
    trend = pick(list(inp.facts), "headcount_trend")
    if trend and isinstance(trend.value, int) and trend.value <= -25:
        out.append(f"shrinking: staff fell {-trend.value}% over the last year (Crustdata headcount history)")
    for f in inp.facts:
        if f.field == "headcount" and f.status == "contradicts" and rules.confirmed(list(inp.facts), "confirm_headcount"):
            out.append(f"corrected: the applicant accepted the record's staff figure ({f.value}) after being shown it")
            break
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
    base = dict(hash=decision_hash(inp.resolution.company_id, a.facts, RULES_VERSION, inp.unavailable),
                rules_version=RULES_VERSION, findings=_findings(inp))

    if hold := _resolution_hold(inp, base):
        return hold
    if inp.unavailable:
        return Decision(outcome="hold", hold_reason="evidence_unavailable", steps=a.steps,
                        gate=Gate(blocked=bool(a.missing), missing=a.missing), **base)

    qs = questions(raw, a, optional=inp.questions_asked < MAX_QUESTIONS)
    if a.missing:
        return Decision(outcome="hold", hold_reason="awaiting_answers", gate=Gate(blocked=True, missing=a.missing),
                        steps=a.steps, questions=qs, **base)

    flips = counterfactual.would_flip_if(a.facts, a.steps, a.outcome, lambda fs: assess(fs).outcome)
    priced = a.outcome != "decline" and a.premium is not None
    if priced:  # also show what each finding costs, even when it alone does not change the outcome
        def outcome_and_price(fs):
            x = assess(fs)
            return x.outcome, (x.premium[1] if x.premium else None)
        flips = counterfactual.with_prices(a.facts, a.steps, a.premium[1], outcome_and_price, flips)
    return Decision(outcome=a.outcome, gate=Gate(blocked=False), steps=a.steps, questions=qs if priced else [],
                    premium_inr=a.premium[1] if priced else None,
                    premium_range_inr=(a.premium[0], a.premium[2]) if priced else None,
                    would_flip_if=flips, **base)
