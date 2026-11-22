"""Covers, websites and GSTINs. No network."""
import pytest

from conftest import F
from invariant import gst, build
from invariant.decide import decide
from invariant.normalize import cover_key, clean_domain
from invariant.read_step import extract


def base(cover, **extra):
    fs = [F("id1", "company_identity", "crust:1"),
          F("occ", "occupancy", "garment_stitching"),
          F("cov", "cover_type", cover, origin="declared")]
    for fld, v in extra.items():
        fs.append(F(f"x_{fld}", fld, v, origin="applicant_followup"))
    return fs


# ------------------------------------------------------------------ covers
def test_wc_prices_on_wages_and_never_asks_for_sum_insured(rules):
    d = decide(base("wc", annual_wages_inr=10_000_000), rules)
    assert d.gate["blocked"] is False
    assert d.steps[0].rule == "WC_BASE_GARMENT_STITCHING"
    # fire-only loadings do not touch workmen's comp
    assert not any(s.rule in ("PROTECTION_UNKNOWN", "CONSTRUCTION_UNKNOWN") for s in d.steps)


def test_wc_without_wages_blocks_on_wages_not_sum_insured(rules):
    d = decide(base("wc"), rules)
    assert d.gate["missing"] == ["annual_wages_inr"]


def test_marine_prices_on_shipments(rules):
    d = decide(base("marine_cargo", annual_shipments_inr=50_000_000), rules)
    assert d.gate["blocked"] is False and d.steps[0].rule.startswith("MARINE_CARGO_BASE_")


def test_burglary_uses_its_own_table_and_skips_fire_protection(rules):
    fire = decide(base("fire", sum_insured_inr=50_000_000), rules)
    burg = decide(base("burglary", sum_insured_inr=50_000_000), rules)
    assert burg.steps[0].rule == "BURGLARY_BASE_GARMENT_STITCHING"
    assert burg.premium_inr != fire.premium_inr
    assert not any(s.rule == "PROTECTION_UNKNOWN" for s in burg.steps)
    assert any(s.rule == "CONSTRUCTION_UNKNOWN" for s in burg.steps)


def test_cover_changes_the_hash(rules):
    a = decide(base("fire", sum_insured_inr=50_000_000), rules).hash
    b = decide(base("burglary", sum_insured_inr=50_000_000), rules).hash
    assert a != b


@pytest.mark.parametrize("said,key", [("Workmen's compensation", "wc"), ("WC", "wc"),
    ("burglary and theft", "burglary"), ("marine transit", "marine_cargo"),
    ("cargo", "marine_cargo"), ("fire and allied perils", "fire"), ("property", "fire")])
def test_cover_names_collapse(said, key):
    assert cover_key(said) == key


# ------------------------------------------------------------------ websites
@pytest.mark.parametrize("raw,clean", [("https://www.Rajda.in/about", "rajda.in"),
    ("rajda.in", "rajda.in"), ("WWW.SNOWMAN.IN", "snowman.in"), ("not a site", None)])
def test_domains_are_cleaned(raw, clean):
    assert clean_domain(raw) == clean


def test_reader_finds_website_but_not_email():
    assert extract("leather maker at rajda.in, 120 staff", backend="stub").domain == "rajda.in"
    assert extract("write to ops@rajda.in, 40 staff", backend="stub").domain is None


def test_reader_does_not_swallow_words_before_the_name():
    f = extract("Workmen compensation for Gokaldas Exports Ltd, 2000 workers, annual wages 48 cr",
                backend="stub")
    assert f.company_name == "Gokaldas Exports Ltd"
    assert f.cover_type == "wc" and f.annual_wages_inr == 480_000_000


# ------------------------------------------------------------------ GSTIN
def test_gstin_check_digit():
    assert gst.parse("27AAPFU0939F1ZV")["valid_check_digit"] is True   # published sample
    assert gst.parse("27AAPFU0939F1ZX")["valid_check_digit"] is False  # one character off
    assert gst.parse("not a gstin") is None


def test_bad_check_digit_is_a_contradiction():
    fs = build.gstin_facts("27AAPFU0939F1ZX", "Acme Pvt Ltd")
    chk = next(f for f in fs if f.field == "gstin_valid")
    assert chk.status == "contradicts" and chk.value is False


def test_company_name_on_a_firm_gstin_is_flagged():
    fs = build.gstin_facts("27AAPFU0939F1ZV", "Acme Exports Pvt Ltd")   # 'F' = firm
    assert any(f.field == "legal_form" and f.status == "contradicts" for f in fs)
    # a name with no legal suffix makes no claim, so nothing to contradict
    assert not any(f.field == "legal_form" for f in build.gstin_facts("27AAPFU0939F1ZV", "Acme"))


def test_gst_state_elsewhere_is_context_never_a_mismatch():
    fs = build.gstin_facts("27AAPFU0939F1ZV", None, "Delhi")
    st = next(f for f in fs if f.field == "gst_state")
    assert st.value == "Maharashtra" and st.status == "consistent_unconfirmed"


# ------------------------------------------------------------------ reader routing
def test_gemini_key_picks_gemini_and_ignores_a_claude_model_name(monkeypatch):
    from invariant import read_step
    seen = {}
    def fake(prompt, model, key=None):
        seen["model"] = model
        return {"company_name": "Acme Pvt Ltd", "declared_headcount": 40}
    monkeypatch.setattr(read_step, "_gemini", fake)
    monkeypatch.delenv("READ_BACKEND", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.setenv("READ_MODEL", "claude-sonnet-4-5")      # stale line in .env
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    f = read_step.extract("anything")
    assert seen["model"] == read_step.GEMINI_DEFAULT_MODEL
    assert f.company_name == "Acme Pvt Ltd" and f.declared_headcount == 40
    monkeypatch.setenv("GEMINI_MODEL", "gemini-pro-latest")
    read_step.extract("anything")
    assert seen["model"] == "gemini-pro-latest"
