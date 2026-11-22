"""Decide layer: hand-built facts mirroring tests/cases/cases.json."""
from __future__ import annotations

import random as _shuffle_only  # test-side only; decide/ must never import random

import pytest

from invariant.contracts import Candidate, DecideInput, Resolution
from invariant.decide.engine import RULES_VERSION, decide
from invariant.shapes import Fact, Source

FETCHED = "2026-11-22T12:00:00+05:30"
RESOLVED = Resolution(status="resolved", company_id="cd_1", name="X", domain="x.example")


def other_qs(d):
    """Questions except claims history, which is always asked (no public record exists)."""
    return [q for q in d.questions if q.field != "claims_history"]


def declared(field, value):
    return Fact(id=f"declared_{field}", field=field, value=value, origin="declared", evidence_kind="claim",
                status="consistent_unconfirmed",
                source=Source(what="applicant prompt", fetched=FETCHED, quote=f"declared_{field}: {value}"))


def followup(field, value, id=None):
    if value is None:
        return Fact(id=id or f"followup_{field}", field=field, origin="applicant_followup",
                    evidence_kind="claim", status="cannot_verify")
    return Fact(id=id or f"followup_{field}", field=field, value=value, origin="applicant_followup",
                evidence_kind="claim", status="consistent_unconfirmed",
                source=Source(what="applicant follow-up", fetched=FETCHED, quote=f"followup_{field}: {value}"))


def ev(id, field, value, status, origin="crustdata", kind="direct", dated=None, match="company_id"):
    return Fact(id=id, field=field, value=value, origin=origin, evidence_kind=kind, status=status,
                company_match=match,
                source=Source(what=f"{origin} record", fetched=FETCHED, dated=dated, quote=f"{field}: {value}"))


def run(facts, resolution=RESOLVED, **kw):
    return decide(DecideInput(resolution=resolution, facts=facts, **kw))


def rules_of(d):
    return [s.rule for s in d.steps]


# ------------------------------------------------------------------ cases

def hero_facts():
    return [
        declared("occupancy", "leather"), declared("headcount", 120), declared("sites", 3),
        ev("crustdata_headcount", "headcount", 310, "contradicts", kind="lower_bound"),
        ev("crustdata_sites", "sites", 4, "contradicts"),
        ev("crustdata_sites_2", "sites", "Chennai", "undeclared"),
        ev("crustdata_occupancy", "occupancy", "leather", "matches"),
        ev("jobs_hazardous_activity_1", "hazardous_activity",
           {"activity": "chrome tanning", "job_title": "Chrome Tanning Supervisor"}, "undeclared"),
    ]


HERO_ANSWERS = [followup("cover_type", "fire_wc"), followup("sum_insured", 50_000_000)]


def clean_facts():
    return [
        declared("occupancy", "footwear"), declared("headcount", 85), declared("sites", 1),
        declared("cover_type", "fire"), declared("sum_insured", 30_000_000),
        ev("crustdata_headcount", "headcount", 80, "consistent_unconfirmed", kind="lower_bound"),
        ev("crustdata_sites", "sites", 1, "matches"),
        ev("crustdata_occupancy", "occupancy", "footwear", "matches"),
    ]


def test_hero_before_answers_holds_for_cover_and_sum_insured():
    d = run(hero_facts())
    assert d.outcome == "hold" and d.hold_reason == "awaiting_answers"
    assert d.gate.blocked and d.gate.missing == ["cover_type", "sum_insured"]
    assert d.premium_inr is None
    # verification still ran: the gap rules are visible while blocked
    assert {"HEADCOUNT_UNDERSTATED", "UNDECLARED_SITE", "UNDECLARED_HAZARD"} <= set(rules_of(d))
    assert [q.field for q in d.questions][:2] == ["cover_type", "sum_insured"]
    assert d.questions[0].options == ["fire", "wc", "fire_wc"]


def test_hero_after_answers_refers_with_flip_on_headcount():
    d = run(hero_facts() + HERO_ANSWERS)
    assert d.outcome == "refer"
    assert {"HEADCOUNT_UNDERSTATED", "UNDECLARED_SITE", "UNDECLARED_HAZARD"} <= set(rules_of(d))
    assert d.premium_inr and d.premium_range_inr[0] <= d.premium_inr <= d.premium_range_inr[1]
    hc = [f for f in d.would_flip_if if f.fact == "crustdata_headcount"]
    assert hc and "150" in hc[0].change and hc[0].then == "quote"
    step = next(s for s in d.steps if s.rule == "HEADCOUNT_UNDERSTATED")
    assert step.multiplier == 1.35 and "crustdata_headcount" in step.because
    assert d.rules_version == RULES_VERSION


def test_headcount_alone_flips_at_declared_x_1_25():
    facts = [f for f in hero_facts() if f.field not in ("hazardous_activity",) and f.id != "crustdata_sites_2"]
    d = run(facts + HERO_ANSWERS)
    assert d.outcome == "refer"
    assert d.would_flip_if[0].fact == "crustdata_headcount"
    assert d.would_flip_if[0].change == "record headcount at or below 150"
    assert d.would_flip_if[0].then == "quote"


def test_clean_quotes_with_no_rules():
    d = run(clean_facts())
    assert d.outcome == "quote" and d.steps == [] and d.would_flip_if == []
    # 3 Cr x (0.90 + 0.15) per mille = 31,500 + 18% GST
    assert d.premium_inr == 37_170
    assert other_qs(d) == []


def test_hidden_hazard_refers():
    facts = [
        declared("occupancy", "garments"), declared("headcount", 200), declared("sites", 2),
        declared("cover_type", "fire"), declared("sum_insured", 80_000_000),
        ev("crustdata_headcount", "headcount", 210, "consistent_unconfirmed", kind="lower_bound"),
        ev("crustdata_sites", "sites", 1, "consistent_unconfirmed"),
        ev("jobs_hazardous_activity_1", "hazardous_activity",
           {"activity": "boiler operation", "job_title": "Boiler Operator (Night Shift)"}, "undeclared"),
        ev("jobs_hazardous_activity_2", "hazardous_activity",
           {"activity": "dyeing", "job_title": "Dyeing Machine Operator"}, "undeclared"),
    ]
    d = run(facts)
    assert d.outcome == "refer" and rules_of(d) == ["UNDECLARED_HAZARD"]
    assert d.steps[0].because == ["jobs_hazardous_activity_1", "jobs_hazardous_activity_2"]


def bad_news_facts(date="2026-10-14", type_="fire"):
    return [
        declared("occupancy", "leather"), declared("headcount", 150), declared("sites", 2),
        declared("cover_type", "fire"), declared("sum_insured", 100_000_000),
        ev("crustdata_headcount", "headcount", 160, "consistent_unconfirmed", kind="lower_bound"),
        ev("crustdata_sites", "sites", 2, "matches"),
        ev("web_adverse_event_1", "adverse_event",
           {"type": type_, "title": "Major fire at Vellore Tanners unit in Ranipet", "date": date},
           "undeclared", origin="web", dated=date, match="name_city"),
    ]


def test_bad_news_declines():
    d = run(bad_news_facts())
    assert d.outcome == "decline" and "CONFIRMED_FIRE" in rules_of(d)
    assert d.premium_inr is None
    assert d.would_flip_if and d.would_flip_if[0].fact == "web_adverse_event_1"
    assert d.would_flip_if[0].then == "quote"


def test_old_fire_or_other_event_is_a_loading_not_decline():
    other = run(bad_news_facts(type_="pollution"))
    assert other.outcome == "refer" and "ADVERSE_EVENT" in rules_of(other)
    # an old fire: newest dated fact is 2026-10, so a 2023 fire is outside 24 months
    facts = bad_news_facts(date="2023-01-10") + [
        ev("web_adverse_event_2", "adverse_event", {"type": "strike", "title": "Strike", "date": "2026-10-01"},
           "undeclared", origin="web", dated="2026-10-01", match="name_city")]
    d = run(facts)
    assert "CONFIRMED_FIRE" not in rules_of(d) and d.outcome == "refer"


def test_sanctions_declines():
    d = run(clean_facts() + [ev("registry_sanctions_1", "sanctions", {"match": True, "caption": "X"},
                                "contradicts", origin="registry")])
    assert d.outcome == "decline" and "SANCTIONS_MATCH" in rules_of(d)


def test_lookalike_holds_with_both_candidates():
    res = Resolution(status="ambiguous", candidates=[
        Candidate(company_id="a", name="Shree Balaji Exports", location="Jaipur, Rajasthan",
                  domain="balajijaipur.example", confidence=0.81),
        Candidate(company_id="b", name="Shree Balaji Exports", location="Surat, Gujarat",
                  domain="balajisurat.example", confidence=0.79)])
    facts = [declared("headcount", 60), declared("cover_type", "fire"), declared("sum_insured", 20_000_000)]
    d = run(facts, resolution=res)
    assert d.outcome == "hold" and d.hold_reason == "ambiguous_company"
    assert len(d.candidates) == 2 and isinstance(d.candidates[0], dict)
    assert len(d.questions) == 1 and d.questions[0].field == "company"
    assert "Jaipur" in d.questions[0].ask and "Surat" in d.questions[0].ask


def test_not_found_asks_for_website_or_city():
    d = run([declared("headcount", 60)], resolution=Resolution(status="not_found"))
    assert d.hold_reason == "company_not_found" and "website or city" in d.questions[0].ask


def nobody_facts():
    return [
        declared("occupancy", "brassware"), declared("headcount", 45), declared("sites", 1),
        declared("cover_type", "fire"), declared("sum_insured", 20_000_000),
        ev("crustdata_headcount", "headcount", 40, "consistent_unconfirmed", kind="lower_bound"),
        ev("crustdata_sites", "sites", 1, "matches"),
        Fact(id="registry_claims_history_1", field="claims_history", origin="registry", evidence_kind="direct",
             status="cannot_verify", company_match="company_id"),
    ]


def test_nobody_can_answer_quotes_with_claims_loading_and_question():
    d = run(nobody_facts())
    assert d.outcome == "quote" and rules_of(d) == ["CLAIMS_HISTORY_UNKNOWN"]
    assert [q.field for q in d.questions] == ["claims_history"]
    q = d.questions[0]
    assert q.options == ["yes", "no"] and q.worth_inr > 0 and "claims" in q.record_we_need
    # applicant says "don't know": loading stays, ladder exhausted, no more claims question
    d2 = run(nobody_facts() + [followup("claims_history", None)])
    assert d2.outcome == "quote" and rules_of(d2) == ["CLAIMS_HISTORY_UNKNOWN"] and d2.questions == []
    # applicant says "no": loading removed
    d3 = run(nobody_facts() + [followup("claims_history", "no")])
    assert d3.steps == [] and d3.premium_inr < d.premium_inr


def test_unavailable_source_holds():
    d = run(clean_facts(), unavailable=["web_search"])
    assert d.outcome == "hold" and d.hold_reason == "evidence_unavailable" and d.premium_inr is None
    assert any("web_search" in f for f in d.findings)
    d2 = run(clean_facts(), resolution=Resolution(status="unavailable"))
    assert d2.hold_reason == "evidence_unavailable"


def test_injection_flag_changes_nothing_but_findings():
    a = run(clean_facts())
    b = run(clean_facts(), injection_attempt=True)
    assert a.hash == b.hash
    assert a.model_dump(exclude={"findings"}) == b.model_dump(exclude={"findings"})
    assert any(f.startswith("injection_attempt") for f in b.findings)


def test_fact_order_and_fetch_time_do_not_change_hash():
    facts = hero_facts() + HERO_ANSWERS
    shuffled = list(facts)
    _shuffle_only.Random(7).shuffle(shuffled)
    later = [f.model_copy(update={"source": f.source.model_copy(update={"fetched": "2026-11-23T09:00:00+05:30"})})
             if f.source else f for f in shuffled]
    a, b, c = run(facts), run(shuffled), run(later)
    assert a.hash == b.hash == c.hash
    assert a.model_dump() == b.model_dump()


def test_questions_asked_does_not_change_hash():
    assert run(hero_facts()).hash == run(hero_facts(), questions_asked=3).hash


# ------------------------------------------------------------------ ladders

def no_si_facts():
    return [f for f in clean_facts() if f.field != "sum_insured"]


COMPONENTS = ["building_owned", "building_area_sqft", "roof_type", "monthly_sales", "stock_weeks", "machinery_value"]


def test_sum_insured_unknown_drops_to_component_questions():
    d = run(no_si_facts() + [followup("sum_insured", None)])
    assert d.outcome == "hold" and d.gate.missing == ["sum_insured"]
    assert sorted(q.field for q in other_qs(d)) == sorted(COMPONENTS)
    assert all(q.rung == 2 for q in other_qs(d))
    roof = next(q for q in d.questions if q.field == "roof_type")
    assert roof.options == ["concrete", "tin_sheet", "other"]


def test_components_answered_give_derived_sum_insured():
    answers = [followup("sum_insured", None), followup("building_owned", "owned"),
               followup("building_area_sqft", {"low": 15000, "high": 20000}), followup("roof_type", "tin_sheet"),
               followup("monthly_sales", 3_000_000)]
    partial = run(no_si_facts() + answers)
    # sum insured is derivable now (machinery and stock from norms); the remaining components
    # are still offered because they narrow the range, and the total is not re-asked
    assert partial.outcome == "quote" and not partial.gate.blocked
    # machinery (2.55-5.1 Cr norm range) is worth asking; stock weeks moves the premium < Rs 5,000
    assert [q.field for q in other_qs(partial)] == ["machinery_value"]
    assert other_qs(partial)[0].worth_inr >= 5000 and partial.questions[0].rung == 2
    answers += [followup("stock_weeks", None), followup("machinery_value", None)]
    d = run(no_si_facts() + answers)
    assert other_qs(d) == []
    assert d.outcome == "quote"
    assert [s.rule for s in d.steps] == ["DERIVED_VALUE"]
    assert d.steps[0].because == ["derived_sum_insured"] and d.steps[0].multiplier == 1.05
    lo, hi = d.premium_range_inr
    assert lo < d.premium_inr < hi
    # the derived fact itself: building 1.725-2.3 Cr, machinery 85 x 3-6 lakh, stock 30L x 6-10 wk / 4.3
    from invariant.decide.derive import derive
    derived = {f.id: f for f in derive(no_si_facts() + answers)}
    si = derived["derived_sum_insured"]
    assert si.derivation.range == pytest.approx((17_250_000 + 25_500_000 + 3_000_000 * 6 / 4.3,
                                                 23_000_000 + 51_000_000 + 3_000_000 * 10 / 4.3))
    assert si.value == round(sum(si.derivation.range) / 2)
    assert si.source.what.startswith("derived: ") and "sq ft" in derived["derived_building_value"].source.quote
    # same answers -> same hash; the derived value is in it
    assert run(no_si_facts() + answers).hash == d.hash


def test_rented_building_is_zero_and_everything_skipped_reaches_band():
    answers = [followup("sum_insured", None), followup("building_owned", "rented"),
               followup("building_area_sqft", None), followup("roof_type", None),
               followup("monthly_sales", None), followup("stock_weeks", None), followup("machinery_value", None)]
    d = run(no_si_facts() + answers)
    assert d.outcome == "hold"
    assert [(q.field, q.rung) for q in other_qs(d)] == [("sum_insured", 3)]
    assert other_qs(d)[0].options == ["<1 Cr", "1-5 Cr", "5-25 Cr", "25+ Cr"]
    band = followup("sum_insured", {"low": 10_000_000, "high": 50_000_000}, id="followup_sum_insured_2")
    d2 = run(no_si_facts() + answers + [band])
    assert d2.outcome == "quote" and "DERIVED_VALUE" in rules_of(d2)


def test_wages_ladder_and_unknown_loading():
    facts = [f for f in clean_facts() if f.field != "cover_type"] + [declared("cover_type", "fire_wc")]
    d = run(facts)
    assert d.questions and d.questions[0].field == "wages" and d.questions[0].worth_inr >= 5000
    d2 = run(facts + [followup("wages", None)])
    assert [q.field for q in other_qs(d2)] == ["pf_monthly"]
    d3 = run(facts + [followup("wages", None), followup("pf_monthly", 120_000)])
    assert rules_of(d3) == [] and other_qs(d3) == []
    # 1,20,000 PF / 0.12 x 12 = 1.2 Cr wages x 3.0 per 100 + fire 31,500, + 18% GST
    assert d3.premium_inr == round((12_000_000 * 0.03 + 31_500) * 1.18)
    d4 = run(facts + [followup("wages", None), followup("pf_monthly", None)])
    assert "UNKNOWN_WAGES" in rules_of(d4) and d4.premium_inr > d.premium_inr


def test_questions_stop_after_five():
    d = run(no_si_facts() + [followup("sum_insured", None)], questions_asked=5)
    assert d.questions == [] and d.outcome == "hold"


def test_cheap_questions_are_dropped_but_blocking_ones_kept():
    d = run(hero_facts())
    assert all(q.worth_inr >= 5000 or q.field in ("cover_type", "sum_insured", "claims_history") for q in d.questions)


def test_decide_is_deterministic():
    facts = hero_facts() + HERO_ANSWERS
    assert run(facts).model_dump() == run(facts).model_dump()


def test_claims_history_always_asked_but_loaded_only_when_unknown():
    d = run(clean_facts())
    q = [q for q in d.questions if q.field == "claims_history"]
    assert q and q[0].worth_inr > 0 and d.outcome == "quote" and rules_of(d) == []
