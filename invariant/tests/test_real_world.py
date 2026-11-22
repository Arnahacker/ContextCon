"""Each test here is a wrong finding seen on LIVE Crustdata data on 2026-11-22.

No network: identity and site logic are fed the shapes that came back.
"""
import pytest

from invariant import build
from invariant.identity import break_tie, exact_name_match
from invariant.pipeline import apply_rules_patch, BadRulesPatch, load_rules, price_build
from invariant.decide import decide
from conftest import F


def cand(name, domain=None, cid=1):
    return {"company_id": cid, "name": name, "domain": domain, "score": 0.8, "_cd": {}}


# ------------------------------------------------------------------ identity
def test_duplicate_profiles_of_one_company_resolve_to_the_richest():
    tied = [cand("Snowman Logistics Limited", None, 4623),
            cand("Snowman Logistics Limited", "snowman.in", 6273357)]
    assert break_tie(tied, "Snowman Logistics Limited")["company_id"] == 6273357


def test_exact_name_given_breaks_a_tie_with_a_subsidiary():
    tied = [cand("Gokaldas Exports Limited", "gokaldasexports.com", 1723),
            cand("Gokaldas Exports Ltd.", None, 10516705),
            cand("GOKALDAS EXPORTS APPAREL AND TEXTILE PARK PRIVATE LIMITED", None, 30562507)]
    assert break_tie(tied, "Gokaldas Exports Ltd")["company_id"] == 1723


def test_different_companies_with_no_exact_name_still_hold():
    # "Superhouse Limited" asked; none of these IS Superhouse Limited
    tied = [cand("Superhouse Leathers Limited", "superhourseleather.com", 1),
            cand("SUPERHOUSE (UK) LIMITED", None, 2),
            cand("SUPERHOUSE ACCESSORIES LIMITED", None, 3)]
    assert break_tie(tied, "Superhouse Limited") is None


def test_truncated_name_never_picks_among_four_rajdas():
    tied = [cand("Rajda Industries & Exports Pvt. Ltd.", "rajda.in", 5285338),
            cand("Rajda Industries & Export Private Limited", "indiamart.com", 25160740),
            cand("Rajda Narrow Fabric Industries", None, 3)]
    assert break_tie(tied, "Rajda Industries") is None
    assert break_tie(tied, "Rajda Industries Exports Pvt Ltd")["company_id"] == 5285338


def test_top_match_with_a_richer_duplicate_uses_the_richer_profile():
    from invariant.identity import resolve
    from invariant.schemas import Form
    thin = {**cand("Gokaldas Exports Ltd.", None, 10516705), "score": 1.0}
    rich = {**cand("Gokaldas Exports Limited", "gokaldasexports.com", 1723), "score": 0.6}
    other = {**cand("Shahi Exports Pvt Ltd", "shahi.co.in", 26067), "score": 0.6}

    class Fake:
        def identify(self, names=None, domains=None):
            return [{"matches": [{"confidence_score": c["score"],
                                  "company_data": {"crustdata_company_id": c["company_id"],
                                                   "basic_info": {"name": c["name"],
                                                                  "primary_domain": c["domain"]}}}
                                 for c in (thin, rich, other)]}]
    got = resolve(Form(company_name="Gokaldas Exports Ltd"), Fake())
    assert got.company["company_id"] == 1723


def test_exact_legal_name_beats_a_higher_scored_plant_profile():
    plant = {**cand("Sudarshan Chemical Industries Limited, Roha And Mahad", None, 19933708)}
    real = {**cand("Sudarshan Chemical Industries Ltd.", "sudarshan.com", 4826), "score": 0.6}
    other = {**cand("Sitara Chemical Industries Limited", "sitara.com.pk", 9), "score": 0.6}
    got = exact_name_match([plant, real, other], "Sudarshan Chemical Industries Limited", plant)
    assert got["company_id"] == 4826
    # no exact match anywhere -> no override
    assert exact_name_match([plant, other], "Sudarshan Chemicals", plant) is None


# ------------------------------------------------------------------ job sites
def job(city, country="India", raw=None, title="Operator"):
    return {"title": title, "city": city, "country": country,
            "location": raw or f"{city}, {country}", "url": "https://x", "posted": "2026-11-01"}


def test_same_city_at_another_granularity_is_not_a_new_site():
    fs = build.job_location_facts([job("Greater Bengaluru Area"), job("Bengaluru Urban"),
                                   job("Bangalore")], ["Bengaluru"], 5)
    assert fs == []


def test_jobs_abroad_are_context_not_premises():
    fs = build.job_location_facts([job("Shanghai", "China"), job("Sao Paulo", "Brazil")],
                                  ["Pune"], 2, "India")
    assert [f.field for f in fs] == ["hiring_abroad"]
    assert not any(f.status == "undeclared" for f in fs)


def test_new_city_within_declared_count_is_not_a_contradiction():
    fs = build.job_location_facts([job("Roha", raw="Roha, Maharashtra, India"),
                                   job("Mumbai", raw="Mumbai, Maharashtra, India")],
                                  ["Pune"], 2)
    # declared 2: Pune + Roha fit, Mumbai is the one past the count
    assert [(f.field, f.value) for f in fs] == [("hiring_location", "Roha"),
                                                ("undeclared_site", "Mumbai")]


def test_declared_industry_is_not_an_undeclared_hazard():
    jobs = [{"title": "Chemical plant operator", "url": "https://x"}]
    assert build.hazard_facts(jobs, ["chemical"]) == []
    assert [f.value for f in build.hazard_facts(jobs, ["garment stitching"])] == ["chemical handling"]


# ------------------------------------------------------------------ editable rules
def test_rules_patch_moves_the_version_and_so_the_hash(rules):
    facts = [F("id1", "company_identity", "crust:1"), F("occ", "occupancy", "leather_tanning"),
             F("si", "sum_insured_inr", 50_000_000, origin="applicant_followup"),
             F("cov", "cover_type", "fire", origin="declared")]
    edited = apply_rules_patch(rules, {"occupancy_rate_per_mille.leather_tanning": 1.5})
    a, b = decide(facts, rules), decide(facts, edited)
    assert edited["version"] != rules["version"]
    assert b.premium_inr > a.premium_inr and a.hash != b.hash
    # same patch -> same version -> same hash: still a pure function
    again = apply_rules_patch(rules, {"occupancy_rate_per_mille.leather_tanning": 1.5})
    assert decide(facts, again).hash == b.hash


@pytest.mark.parametrize("patch", [{"loadings.NEW_RULE.multiplier": 2},
                                   {"loadings.UNDECLARED_HAZARD.explain": 2},
                                   {"version": 1}, {"gst_rate": "abc"}, {"gst_rate": -1}])
def test_rules_patch_cannot_add_rules_or_change_text(rules, patch):
    with pytest.raises(BadRulesPatch):
        apply_rules_patch(rules, patch)


def test_price_build_reconciles_with_decide(rules):
    facts = [F("id1", "company_identity", "crust:1"), F("occ", "occupancy", "leather_tanning"),
             F("si", "sum_insured_inr", 50_000_000, origin="applicant_followup"),
             F("cov", "cover_type", "fire", origin="declared"),
             F("c1", "certification", "ISO_14001")]
    d = decide(facts, rules).to_dict()
    pb = price_build(d, rules)
    assert pb[0]["kind"] == "base" and pb[-1]["label"] == "GST"
    assert pb[-1]["after"] == d["premium_inr"]
    assert all(r["kind"] != "error" for r in pb)


# ------------------------------------------------------------------ mock fixtures
def test_mock_mode_serves_the_company_asked_for(tmp_path, monkeypatch):
    """Mock mode used to answer every name with the Rajda mock."""
    monkeypatch.setenv("CRUSTDATA_MODE", "mock")
    monkeypatch.setenv("READ_BACKEND", "stub")
    from invariant import runlog
    monkeypatch.setattr(runlog, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(runlog, "CACHE", tmp_path / "cache")
    from invariant.pipeline import run
    from invariant.examples import EXAMPLES
    ex = next(e for e in EXAMPLES if "Sudarshan" in e["prompt"])
    case = run(ex["prompt"])
    assert case["identity"]["company"]["company_id"] == 4826
    assert "Sudarshan" in case["identity"]["company"]["name"]
