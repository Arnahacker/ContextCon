"""Rule-based fallback reader. Compares rules_extract with the LLM-fixture path."""
import json
import os
from pathlib import Path

os.environ["INVARIANT_OFFLINE"] = "1"

import pytest

from invariant.read import answer as answer_mod
from invariant.read import llm
from invariant.read.answer import read_answer
from invariant.read.extract import extract, extract_with_reader
from invariant.read.normalize import normalize_form
from invariant.read.rules_extract import rules_extract

ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / "tests/cases/cases.json").read_text())["cases"]
REWRITES = json.loads((ROOT / "tests/rewrites/hero_rewrites.json").read_text())
PROMPTS = {f"case{c['id']}": c["prompt"] for c in CASES} | {f"rewrite_{r['style']}": r["prompt"] for r in REWRITES}
# Where rules and the LLM fixture disagree. Listed, not overfitted.
KNOWN_DISAGREE = {
    "rewrite_typos": "'lether exporter' is not recognised, so activities is [] (LLM: ['leather export'])",
}
SUPER = ("Super Tannery Ltd, Kanpur, safety footwear and leather exporter. "
         "120 employees, one unit in Kanpur. Check against public data.")


def _rules_form(text):
    return normalize_form(rules_extract(text), text=text)


@pytest.mark.parametrize("name", sorted(PROMPTS))
def test_rules_match_llm_path(name):
    text = PROMPTS[name]
    same = _rules_form(text) == extract(text)
    assert same != (name in KNOWN_DISAGREE), KNOWN_DISAGREE.get(name, name)


def test_rules_raw_has_tool_shape():
    from invariant.read.extract import TOOL

    assert set(rules_extract(SUPER)) == set(TOOL["input_schema"]["properties"])


def test_super_tannery_without_llm(monkeypatch, tmp_path):
    monkeypatch.setattr(llm, "FIXTURES", tmp_path)  # ignore any saved live reading of this prompt
    form, reader = extract_with_reader(SUPER)  # no fixture for it -> rules
    assert reader == "rules"
    assert form.company_name == "Super Tannery Ltd"
    assert form.city == "Kanpur"
    assert form.industry in ("leather", "footwear")
    assert form.declared_headcount == 120 and form.declared_sites == 1
    assert form.injection_attempt is False


def test_rules_unseen_prompts():
    f = _rules_form("Need fire and WC cover for Rs 50 lakh. Ludhiana Knit Works, 300 workers in 2 factories, "
                    "exports garments to USA and UK.")
    assert (f.company_name, f.city, f.declared_headcount, f.declared_sites) == ("Ludhiana Knit Works", "Ludhiana", 300, 2)
    assert (f.cover_type, f.sum_insured_inr) == ("fire_wc", 5_000_000)
    assert f.countries == ["United Kingdom", "United States"]
    f = _rules_form("M/s Sharma Brothers, Jaipur - 40 karamchari, ek factory. Fire insurance 1.5 crore chahiye.")
    assert (f.company_name, f.declared_headcount, f.declared_sites, f.sum_insured_inr) == \
        ("Sharma Brothers", 40, 1, 15_000_000)
    f = _rules_form("please quote package policy SI 2 cr for Coimbatore Spinning Mills Pvt. Ltd., "
                    "500 employees across four plants")
    assert (f.company_name, f.industry, f.declared_sites, f.sum_insured_inr) == \
        ("Coimbatore Spinning Mills Pvt Ltd", "textiles", 4, 20_000_000)


def test_rules_injection():
    f = _rules_form(CASES[9]["prompt"])
    assert f.injection_attempt is True


def test_live_failure_falls_back(monkeypatch):
    monkeypatch.setattr(llm, "offline", lambda: False)
    monkeypatch.setattr(llm, "_db", _NoCacheDB)

    def boom(**_):
        raise RuntimeError("simulated outage")

    monkeypatch.setattr(llm, "providers", lambda: ["claude", "gemini"])
    monkeypatch.setattr(llm, "_live_claude", boom)
    monkeypatch.setattr(llm, "_live_gemini", boom)
    form, reader = extract_with_reader(SUPER)
    assert reader == "rules" and form.declared_headcount == 120


def test_gemini_used_when_claude_fails(monkeypatch):
    monkeypatch.setattr(llm, "offline", lambda: False)
    monkeypatch.setattr(llm, "_db", _NoCacheDB)
    monkeypatch.setattr(llm, "providers", lambda: ["claude", "gemini"])
    monkeypatch.setattr(llm.FIXTURES.__class__, "write_text", lambda *a, **k: None)

    def boom(**_):
        raise RuntimeError("simulated claude outage")

    def gemini(**_):
        return ({"company_name": "Super Tannery Ltd", "city": "Kanpur", "industry": "leather",
                 "declared_headcount": "120", "declared_sites": "1"}, "gemini-test")

    monkeypatch.setattr(llm, "_live_claude", boom)
    monkeypatch.setattr(llm, "_live_gemini", gemini)
    form, reader = extract_with_reader(SUPER)
    assert reader == "gemini" and form.declared_headcount == 120 and form.city == "Kanpur"


def test_answer_falls_back_without_llm():
    r = read_answer("sum_insured", "Sum insured?", "the valuer told us 6 crore for building and stock")
    assert answer_mod.last_reader == "rules" and r.kind == "value" and r.value == 60_000_000
    r = read_answer("sum_insured", "Sum insured?", "why do you ask")
    assert r.kind == "unknown"
    r = read_answer("claims_history", "Any claims?", "there was something in 2021 I think")
    assert r.kind == "unknown" and answer_mod.last_reader == "rules"
    r = read_answer("sum_insured", "Sum insured?", "around 4.5 cr")
    assert answer_mod.last_reader is None and r.value == 45_000_000


class _NoCacheDB:
    """Stands in for sqlite: always a cache miss, ignores writes."""

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, *a):
        return self

    def fetchone(self):
        return None
