"""decide() is a pure function. These tests need no network and must stay that way."""
import random, pytest
from conftest import F, src
from invariant.decide import decide, decision_hash
from invariant.facts import Fact, UnsourcedFact

def base_facts():
    return [
        F("id1", "company_identity", "crust:123"),
        F("occ", "occupancy", "leather_tanning"),
        F("si",  "sum_insured_inr", 50_000_000, origin="applicant_followup"),
        F("cov", "cover_type", "fire", origin="declared"),
    ]

def test_clean_case_quotes(rules):
    d = decide(base_facts(), rules)
    assert d.outcome == "quote"
    assert d.premium_inr > 0
    assert d.gate["blocked"] is False

def test_hero_headcount_contradiction_refers(rules):
    f = base_facts() + [
        F("h_dec", "headcount", 120, origin="declared"),
        F("h_cd",  "headcount", 310, status="contradicts", kind="lower_bound"),
    ]
    d = decide(f, rules)
    assert d.outcome == "refer"
    assert any(s.rule == "HEADCOUNT_UNDERSTATED" for s in d.steps)
    # the loading must name the facts that caused it
    step = next(s for s in d.steps if s.rule == "HEADCOUNT_UNDERSTATED")
    assert "h_cd" in step.because and "h_dec" in step.because

def test_no_identity_blocks_the_gate(rules):
    f = [x for x in base_facts() if x.field != "company_identity"]
    d = decide(f, rules)
    assert d.gate["blocked"] is True
    assert "company_identity" in d.gate["missing"]
    assert any(s.rule == "IDENTITY_UNVERIFIED" for s in d.steps)

def test_lookalike_holds_and_never_guesses(rules):
    f = base_facts()
    f[0] = F("id1", "company_identity", None, status="contradicts",
             note="Shakti Leathers (TN) or Shakti Leathers (UP)")
    d = decide(f, rules)
    assert d.outcome == "hold"
    assert d.hold_reason == "ambiguous_company"
    assert d.premium_inr == 0

def test_timeout_holds_silence_is_not_nothing_bad(rules):
    f = base_facts() + [F("ev", "evidence_unavailable", "web/search/live")]
    d = decide(f, rules)
    assert d.outcome == "hold"
    assert d.hold_reason == "evidence_unavailable"

def test_severe_adverse_event_declines(rules):
    f = base_facts() + [F("fire1", "adverse_event_severe", True,
                          origin="web", source=src("thehindu.com", "2026-10-02", "fire at the unit"))]
    d = decide(f, rules)
    assert d.outcome == "decline"
    assert d.steps[0].because == ["fire1"]

def test_certification_is_a_discount(rules):
    f = base_facts() + [F("c1", "certification", "ISO_45001", origin="own_site")]
    d = decide(f, rules)
    assert any(s.rule == "ISO_45001" and s.multiplier < 1 for s in d.steps)
    assert decide(f, rules).premium_inr < decide(base_facts(), rules).premium_inr

def test_unsourced_fact_is_impossible():
    with pytest.raises(UnsourcedFact):
        Fact("x", "headcount", 310, "crustdata", "contradicts")

# ---------------------------------------------------------- the key property
def test_hash_ignores_fact_order(rules):
    f = base_facts()
    a = decide(f, rules).hash
    for _ in range(12):
        random.shuffle(f)
        assert decide(f, rules).hash == a

def test_hash_moves_when_a_fact_moves(rules):
    a = decide(base_facts(), rules).hash
    f = base_facts() + [F("h_cd", "headcount", 310, status="contradicts")]
    assert decide(f, rules).hash != a

def test_decide_is_repeatable(rules):
    f = base_facts()
    runs = [decide(f, rules) for _ in range(25)]
    assert len({r.hash for r in runs}) == 1
    assert len({r.premium_inr for r in runs}) == 1
