"""Parsing checked against REAL Crustdata responses saved on 2026-11-22.

No network: these read mocks/*.json, which are verbatim live responses.
"""
import json, pathlib

from invariant import adapt, build

MOCKS = pathlib.Path(__file__).resolve().parents[1] / "mocks"
RAJDA = 5285338


def load(name):
    return json.loads((MOCKS / name).read_text(encoding="utf-8"))


def test_job_listings_parse_from_real_response():
    resp = load("_real_job_search_sample.json")
    assert adapt.jobs_total(resp) == 551
    js = adapt.jobs(resp)
    assert len(js) == 3
    j = js[0]
    assert j["title"] == "Assistant Director Airline Supply Chain Operations"
    assert j["url"].startswith("https://")
    assert j["posted"] == "2026-11-20"
    assert j["city"] == "Montreal" and j["country"] == "Canada"


def test_jobs_at_another_company_are_dropped():
    # the fuzzy name filter returned IATA and others for "Tata International".
    # A lookalike's job must never become this applicant's hazard or site.
    resp = load("_real_job_search_sample.json")
    assert adapt.jobs(resp, company_id=RAJDA) == []
    # 2 IATA listings; the third has a null company id and is not attributable
    assert len(adapt.jobs(resp, company_id=908443)) == 2


def test_rajda_has_no_jobs_and_that_creates_no_facts():
    js = adapt.jobs(load("job_search.json"), company_id=RAJDA)
    assert js == []
    assert build.hazard_facts(js, []) == []
    assert build.job_location_facts(js, ["Kolkata"]) == []


def test_hazard_matches_title_not_boilerplate_description():
    jobs = [{"title": "HR Executive", "description": "handle chemical safety paperwork"},
            {"title": "Boiler Attendant", "description": "", "url": "https://x/1",
             "posted": "2026-11-01"}]
    fs = build.hazard_facts(jobs, [])
    assert [f.value for f in fs] == ["boiler operation"]
    assert fs[0].source.dated == "2026-11-01"


def test_remote_job_is_not_a_site():
    jobs = [{"title": "Designer", "city": "Milan", "location": "Milan", "remote": True}]
    assert build.job_location_facts(jobs, ["Kolkata"]) == []


def test_real_web_results_naming_rajda_are_not_incidents():
    # live response: a vendor client list and directory pages name
    # "Rajda Industries & Exports" + Kolkata. None of them is a fire.
    resp = load("web_search_live.json")
    assert adapt.web_ok(resp)
    rs = adapt.web_results(resp)
    assert len(rs) == 7 and all(r["url"] for r in rs)
    fs = build.adverse_facts(rs, "Rajda Industries & Exports Pvt. Ltd.", "Kolkata", ["q"])
    assert len(fs) == 1 and fs[0].id == "adverse_none"
    assert fs[0].evidence_kind == "search_negative"


def test_incident_naming_company_and_city_is_found():
    rs = [{"title": "Fire at Rajda Industries & Exports unit in Kolkata",
           "snippet": "", "url": "https://news.example/1"}]
    fs = build.adverse_facts(rs, "Rajda Industries & Exports Pvt. Ltd.", "Kolkata", ["q"])
    assert fs[0].field == "adverse_event" and fs[0].status == "matches"


def test_incident_at_lookalike_in_other_city_is_ignored():
    rs = [{"title": "Fire at Rajda Industries & Exports unit in Chennai",
           "snippet": "", "url": "https://news.example/2"}]
    fs = build.adverse_facts(rs, "Rajda Industries & Exports Pvt. Ltd.", "Kolkata", ["q"])
    assert fs[0].id == "adverse_none"


def test_incomplete_web_search_holds_instead_of_none_found():
    resp = {"success": False, "results": [], "metadata": {"failed_pages": [1]}}
    assert not adapt.web_ok(resp)
    fs = build.adverse_facts(adapt.web_results(resp), "Rajda", "Kolkata", ["q"],
                             complete=adapt.web_ok(resp))
    assert fs[0].field == "evidence_unavailable" and fs[0].status == "cannot_verify"
