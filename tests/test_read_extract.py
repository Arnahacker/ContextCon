import json
import os
from pathlib import Path

os.environ["INVARIANT_OFFLINE"] = "1"

import pytest

from invariant.read import declared_facts, extract

ROOT = Path(__file__).resolve().parents[1]
CASES = {c["id"]: c for c in json.loads((ROOT / "tests/cases/cases.json").read_text())["cases"]}
REWRITES = json.loads((ROOT / "tests/rewrites/hero_rewrites.json").read_text())
FETCHED = "2026-11-22T12:00:00+05:30"


def _subset(form, expected):
    got = form.model_dump()
    return {k: got[k] for k in expected}


@pytest.mark.parametrize("cid", [c for c in CASES if "expected_form" in CASES[c]])
def test_case_expected_form(cid):
    case = CASES[cid]
    assert _subset(extract(case["prompt"]), case["expected_form"]) == case["expected_form"]


def test_hero_has_eight_rewrites_in_distinct_styles():
    assert len(REWRITES) == 8
    assert len({r["style"] for r in REWRITES}) == 8


def test_all_rewrites_give_byte_identical_form():
    hero = extract(CASES[1]["prompt"])
    expected = CASES[1]["expected_form"]
    assert _subset(hero, expected) == expected
    for r in REWRITES:
        assert extract(r["prompt"]).model_dump_json() == hero.model_dump_json(), r["style"]


def test_written_badly_equals_hero():
    assert extract(CASES[8]["prompt"]) == extract(CASES[1]["prompt"])


def test_sent_twice_equals_clean():
    assert extract(CASES[6]["prompt"]) == extract(CASES[2]["prompt"])


def test_injection_flagged_and_otherwise_identical():
    inj, clean = extract(CASES[10]["prompt"]), extract(CASES[2]["prompt"])
    assert inj.injection_attempt is True and clean.injection_attempt is False
    assert inj.model_copy(update={"injection_attempt": False}) == clean


def test_hero_form_fields():
    f = extract(CASES[1]["prompt"])
    assert f.ask == "verify" and f.cover_type is None and f.sum_insured_inr is None
    assert f.countries == [] and f.trade_names == []


def test_declared_facts_canonical_quotes():
    prompts = [CASES[1]["prompt"], CASES[8]["prompt"]] + [r["prompt"] for r in REWRITES]
    hero_facts = declared_facts(extract(CASES[1]["prompt"]), FETCHED)
    for p in prompts:
        facts = declared_facts(extract(p), FETCHED)
        assert facts == hero_facts
        for f in facts:
            assert f.source.quote == f"{f.field}: {f.value}"
            assert f.source.quote not in p or f.field == "company"  # never raw prose
            assert f.id == f"declared_{f.field}" and f.origin == "declared"
            assert f.evidence_kind == "claim" and f.status == "consistent_unconfirmed"
            assert f.source.what == "applicant prompt"
    assert {f.field for f in hero_facts} == {"company", "occupancy", "headcount", "sites"}
    q = {f.field: f.source.quote for f in hero_facts}
    assert q["headcount"] == "headcount: 120" and q["sites"] == "sites: 3"


def test_declared_facts_for_clean_case():
    facts = {f.field: f for f in declared_facts(extract(CASES[2]["prompt"]), FETCHED)}
    assert facts["sum_insured"].source.quote == "sum_insured: 30000000"
    assert facts["cover_type"].value == "fire"
    assert "export_countries" not in facts


def test_offline_missing_fixture_falls_back_to_rules():
    import sys

    extract_mod = sys.modules["invariant.read.extract"]
    from invariant.read.extract import extract_with_reader

    form, reader = extract_with_reader("A totally new prompt with no fixture.")
    assert reader == "rules" and extract_mod.last_reader == "rules"
    assert form.company_name is None
    _, reader = extract_with_reader(CASES[1]["prompt"])
    assert reader == "claude" and extract_mod.last_reader == "claude"
