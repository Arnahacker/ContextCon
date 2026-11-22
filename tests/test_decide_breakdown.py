"""The premium breakdown: base, each loading, minimum, GST -- and it must land on the
engine's own premium to the rupee, or it is not shown at all."""
from __future__ import annotations

from invariant.decide.breakdown import breakdown
from test_decide_engine import (HERO_ANSWERS, clean_facts, declared, followup, hero_facts, run)


def _check(facts):
    d = run(facts)
    b = breakdown(facts)
    assert d.premium_inr is not None, "case should be priced"
    assert b is not None
    assert b["total"] == d.premium_inr
    running = None
    for line in b["lines"]:
        if line["kind"] == "base":
            running = line["running"]
        else:
            assert line["running"] >= 0
    assert b["lines"][-1]["kind"] == "gst" and b["lines"][-1]["running"] == d.premium_inr
    return d, b


def test_quote_breakdown_reconciles():
    d, b = _check(clean_facts())
    kinds = [l["kind"] for l in b["lines"]]
    assert kinds[0] == "base" and kinds[-1] == "gst" and "loading" not in kinds


def test_refer_breakdown_names_every_loading():
    d, b = _check(hero_facts() + HERO_ANSWERS)
    assert d.outcome == "refer"
    rules = {l["rule"] for l in b["lines"] if l["kind"] == "loading"}
    assert {"HEADCOUNT_UNDERSTATED", "UNDECLARED_SITE", "UNDECLARED_HAZARD"} <= rules
    # fire + workmen's comp: both bases are shown
    assert sum(1 for l in b["lines"] if l["kind"] == "base") >= 2


def test_breakdown_is_none_when_not_priced():
    assert breakdown(hero_facts()) is None                      # gate blocked
    assert run(hero_facts()).premium_inr is None


def test_minimum_premium_line_appears_when_it_applies():
    facts = [declared("occupancy", "footwear"), declared("headcount", 5), declared("sites", 1),
             declared("cover_type", "fire"), declared("sum_insured", 1_000_000)]
    d, b = _check(facts)
    assert any(l["kind"] == "minimum" for l in b["lines"])


def test_marine_and_liability_breakdowns_reconcile():
    base = [declared("occupancy", "leather"), declared("headcount", 50), declared("sites", 1)]
    _check(base + [followup("cover_type", "marine"), followup("cargo_value", 20_000_000),
                   followup("marine_route", "international")])
    _check(base + [followup("cover_type", "liability"), followup("liability_limit", 10_000_000),
                   followup("turnover", 300_000_000)])
