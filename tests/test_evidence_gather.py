"""Evidence layer, offline only: fixtures in fixtures/crustdata/, cache in a temp dir."""
from datetime import datetime, timezone

import httpx
import pytest

from invariant.contracts import ALL_FIELDS
from invariant.evidence import facts as F
from invariant.evidence.client import CrustdataClient, EvidenceUnavailable, meter_snapshot
from invariant.evidence.gather import gather
from invariant.evidence.resolve import resolve
from invariant.shapes import Fact, Form

NOW = datetime(2026, 11, 22, 6, 30, tzinfo=timezone.utc)

HERO = Form(company_name="Kanpur Hide Exports Pvt Ltd", city="Kanpur", industry="leather",
            declared_headcount=120, declared_sites=3, activities=["leather export"])
CLEAN = Form(company_name="Agra Footwear Works", city="Agra", industry="footwear", declared_headcount=85,
             declared_sites=1, cover_type="fire", sum_insured_inr=30000000)
HAZARD = Form(company_name="Tiruppur Stitchline Garments", city="Tiruppur", industry="garments",
              declared_headcount=200, declared_sites=2, cover_type="fire", sum_insured_inr=80000000,
              activities=["garment stitching"])
BAD_NEWS = Form(company_name="Vellore Tanners Ltd", city="Ranipet", industry="leather", declared_headcount=150,
                declared_sites=2, cover_type="fire", sum_insured_inr=100000000)
LOOKALIKE = Form(company_name="Shree Balaji Exports", declared_headcount=60, cover_type="fire",
                 sum_insured_inr=20000000)
SUPER = Form(company_name="Super Tannery Ltd", city="Kanpur", industry="leather", declared_headcount=120,
             declared_sites=1, cover_type="fire", sum_insured_inr=50000000)
BRASS = Form(company_name="Moradabad Brassware Co", city="Moradabad", industry="brassware",
             declared_headcount=45, declared_sites=1, cover_type="fire", sum_insured_inr=20000000)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("INVARIANT_FAULT", raising=False)
    monkeypatch.delenv("OPENSANCTIONS_API_KEY", raising=False)
    return CrustdataClient(offline=True, cache_path=tmp_path / "cache.sqlite")


def run(form, client):
    return gather(form, client=client, now=NOW)


def by_field(result, field):
    return [f for f in result.facts if f.field == field]


def test_hero(client):
    r = run(HERO, client)
    assert r.resolution.status == "resolved" and r.resolution.company_id == "700101"
    assert r.unavailable == []
    hc = by_field(r, "headcount")[0]
    assert (hc.value, hc.status, hc.evidence_kind) == (310, "contradicts", "lower_bound")
    assert hc.source.dated == "2026-10-01" and hc.source.quote == "headcount.total: 310"
    sites = {f.id: f for f in by_field(r, "sites")}
    assert sites["crustdata_sites"].value == 4 and sites["crustdata_sites"].status == "contradicts"
    undeclared = {f.value["city"] for f in sites.values() if f.status == "undeclared"}
    assert undeclared == {"Unnao", "Kanpur Dehat", "Chennai"}
    hz = by_field(r, "hazardous_activity")
    assert {h.value["activity"] for h in hz} >= {"tannery"}
    assert all(h.status == "undeclared" and h.source.url.startswith("https://jobs.example/") for h in hz)
    assert by_field(r, "occupancy")[0].status == "matches"


def test_clean_has_no_contradictions(client):
    r = run(CLEAN, client)
    assert r.resolution.status == "resolved" and r.unavailable == []
    assert [f.id for f in r.facts if f.status == "contradicts"] == []
    assert by_field(r, "headcount")[0].status == "consistent_unconfirmed"  # 80 < 85
    assert by_field(r, "sites")[0].status == "matches"
    assert by_field(r, "adverse_event") == []  # "Fire at Agra shoe market" does not name the company
    assert by_field(r, "hazardous_activity") == []


def test_hidden_hazard_boiler_and_dyeing(client):
    r = run(HAZARD, client)
    acts = {f.value["activity"] for f in by_field(r, "hazardous_activity")}
    assert acts == {"boiler", "dyeing"}
    assert by_field(r, "occupancy")[0].value == "garments"
    assert by_field(r, "occupancy")[0].status == "matches"


def test_bad_news_dated_fire_and_lookalike_news_dropped(client):
    r = run(BAD_NEWS, client)
    ev = by_field(r, "adverse_event")
    assert len(ev) == 1  # cooperative in Ambur + tanners association dropped
    f = ev[0]
    assert f.value == {"type": "fire", "title": "Major fire at Vellore Tanners unit in Ranipet", "date": "2026-10-14"}
    assert f.source.dated == "2026-10-14" and f.origin == "web" and f.company_match == "name_city"
    assert f.source.url == "https://news.example/tn/vellore-tanners-ranipet-fire"


def test_news_filter_rules():
    cities = ["Ranipet", "Vellore"]
    assert F.names_company("Major fire at Vellore Tanners unit in Ranipet", "Vellore Tanners Ltd", cities, None)
    # name inside the name does not count as the city
    assert F.names_company("Vellore Tanners Association strike", "Vellore Tanners Ltd", cities, None) is None
    # similar name, right city
    assert F.names_company("Fire at Vellore Tannery in Ranipet", "Vellore Tanners Ltd", cities, None) is None
    assert F.names_company("Vellore Tanners (velloretanners.example) recall", "Vellore Tanners Ltd", [],
                           "velloretanners.example") == "domain"


def test_publish_date_never_invented():
    assert F.publish_date('<meta property="article:published_time" content="2026-10-14T08:30:00+05:30">') == "2026-10-14"
    assert F.publish_date('<script>{"datePublished": "2025-01-02"}</script>') == "2025-01-02"
    assert F.publish_date("<html><body>no date here 2024-01-01</body></html>") is None
    assert F.publish_date(None) is None


def test_web_enrich_failure_keeps_fact_with_null_date(client):
    client._faults = {"web_enrich": "timeout"}
    r = run(BAD_NEWS, client)
    ev = by_field(r, "adverse_event")
    assert len(ev) == 1 and ev[0].source.dated is None and ev[0].value["date"] is None
    assert r.unavailable == []


def test_lookalike_is_ambiguous(client):
    r = run(LOOKALIKE, client)
    assert r.resolution.status == "ambiguous" and r.facts == []
    c = r.resolution.candidates
    assert [x.company_id for x in c] == ["700105", "700106"]
    assert [x.location for x in c] == ["Jaipur, Rajasthan", "Surat, Gujarat"]  # the (U.K.) shell is dropped


def test_lookalike_picked_by_domain_resolves(client):
    r = run(LOOKALIKE.model_copy(update={"domain": "balajisurat.example"}), client)
    assert r.resolution.status == "resolved" and r.resolution.company_id == "700106"
    assert r.unavailable == []


def test_brassware_occupancy(client):
    r = run(BRASS, client)
    occ = by_field(r, "occupancy")[0]
    assert (occ.value, occ.status) == ("brassware", "matches")


def test_not_found(client):
    r = run(Form(company_name="Nobody Fixtured Here"), client)  # no fixture -> unavailable, not a guess
    assert r.resolution.status == "unavailable" and r.unavailable == ["identify"]
    r = run(Form(), client)
    assert r.resolution.status == "not_found"


def test_fault_injection_env(client, monkeypatch):
    monkeypatch.setenv("INVARIANT_FAULT", "web_search:timeout")  # read at call time
    r = run(CLEAN, client)
    assert r.unavailable == ["web_search"]
    assert r.resolution.status == "resolved" and by_field(r, "headcount")  # other sources still ran
    failed = [c for c in r.calls if not c.ok]
    assert len(failed) == 1 and failed[0].endpoint == "/web/search/live"


def test_second_call_is_cached(client):
    before = meter_snapshot()["cached"]
    r1 = run(CLEAN, client)
    r2 = run(CLEAN, client)
    assert not any(c.cached for c in r1.calls)
    assert r2.calls and all(c.cached for c in r2.calls)
    assert [c.request_hash for c in r1.calls] == [c.request_hash for c in r2.calls]
    assert meter_snapshot()["cached"] - before == len(r2.calls)
    snap = meter_snapshot()
    assert {"credits", "calls", "cached", "by_endpoint", "recent"} <= set(snap) and len(snap["recent"]) <= 50
    # same facts apart from fetch time
    strip = lambda r: [f.model_dump(exclude={"source": {"fetched"}}) for f in r.facts]
    assert strip(r1) == strip(r2)


@pytest.mark.parametrize("form", [HERO, CLEAN, HAZARD, BAD_NEWS, LOOKALIKE, BRASS, None])
def test_every_fact_is_valid(client, form):
    r = run(form or SUPER, client)
    ids = [f.id for f in r.facts]
    assert len(ids) == len(set(ids))
    for f in r.facts:
        Fact.model_validate(f.model_dump())
        assert f.field in ALL_FIELDS
        assert f.source and f.source.fetched and f.source.quote
        assert f.origin in ("crustdata", "web", "registry") and f.company_match != "not_applicable"


# ---------------------------------------------------------------- live code path with a mock transport


def test_live_retry_and_credits(tmp_path, monkeypatch):
    monkeypatch.delenv("INVARIANT_FAULT", raising=False)
    seen = []

    def handler(req):
        seen.append(req)
        if len(seen) < 3:
            return httpx.Response(503, headers={"x-credits-used": "0"})
        return httpx.Response(200, json=[{"matched_on": "x", "matches": []}], headers={"x-credits-used": "0.2"})

    c = CrustdataClient(api_key="k", offline=False, cache_path=tmp_path / "c.sqlite",
                        transport=httpx.MockTransport(handler))
    c.sleep = lambda s: None
    data, rec = c.post("/company/identify", {"names": ["X"]})
    assert len(seen) == 3 and rec.ok and rec.credits == 0.2 and not rec.cached
    assert seen[0].headers["authorization"] == "Bearer k" and seen[0].headers["x-api-version"] == "2025-11-01"
    _, rec2 = c.post("/company/identify", {"names": ["X"]})
    assert rec2.cached and len(seen) == 3


def test_live_gives_up_after_retries(tmp_path, monkeypatch):
    monkeypatch.delenv("INVARIANT_FAULT", raising=False)
    calls = []

    def handler(req):
        calls.append(1)
        raise httpx.ReadTimeout("slow", request=req)

    c = CrustdataClient(api_key="k", offline=False, cache_path=tmp_path / "c.sqlite",
                        transport=httpx.MockTransport(handler))
    c.sleep = lambda s: None
    with pytest.raises(EvidenceUnavailable) as e:
        c.post("/web/search/live", {"query": "q"})
    assert len(calls) == 4 and e.value.source == "web_search" and "timeout" in e.value.reason
    assert not e.value.record.ok


def test_sanctions_only_matches_become_facts():
    resp = {"responses": {"q": {"results": [
        {"id": "NK-1", "caption": "Acme Leathers", "score": 0.91, "match": True, "datasets": ["x"]},
        {"id": "NK-2", "caption": "Acme Lighting", "score": 0.4, "match": False}]}}}
    fs = F.sanctions_facts(resp, "2026-11-22T00:00:00+00:00")
    assert len(fs) == 1 and fs[0].status == "contradicts" and fs[0].value["match"] is True


# ---------------------------------------------------------------- real demo company (live samples)


def test_super_tannery_from_live_samples(client):
    r = run(SUPER, client)
    assert r.resolution.status == "resolved" and r.resolution.company_id == "4889"
    assert r.resolution.domain == "supertannery.com" and r.unavailable == []
    hc = by_field(r, "headcount")[0]
    assert (hc.value, hc.status, hc.source.dated) == (200, "contradicts", "2026-11-02")  # 200 > 120*1.25
    occ = by_field(r, "occupancy")[0]
    assert (occ.value, occ.status) == ("leather", "matches")  # "Manufacturing" alone says nothing; name says tannery
    job_sites = [f for f in by_field(r, "sites") if f.id.startswith("jobs_")]
    assert [f.value["city"] for f in job_sites] == ["Unnao"]
    assert job_sites[0].source.url.startswith("https://in.indeed.com/")
    # enrich carried news, so no web search was spent
    assert "/web/search/live" not in [c.endpoint for c in r.calls]
    assert by_field(r, "adverse_event") == []  # results, ratings, AGM: none adverse


def test_super_tannery_name_variants_resolve_same(client):
    for name in ["Super Tannery Limited", "super tannery ltd"]:
        r = run(SUPER.model_copy(update={"company_name": name, "industry": None}), client)
        assert r.resolution.company_id == "4889"


def test_resolution_filters():
    from invariant.evidence.resolve import plausible

    def m(cid, name, dom, rng, ind, conf=0.8, desc=""):
        return {"confidence_score": conf, "company_data": {"crustdata_company_id": cid, "basic_info": {
            "name": name, "primary_domain": dom, "employee_count_range": rng, "industries": ind, "description": desc}}}

    ms = [m(1, "Super Tannery Limited", "supertannery.com", "201-500", ["Manufacturing"]),
          m(2, "Super Tannery Ltd - India", None, None, ["Software Development"]),            # shell
          m(3, "SUPER TANNERY (U.K.) LIMITED", None, None, ["Textile Manufacturing"]),        # shell + foreign
          m(4, "Super Tannery Limited Fashion Shoe", "supertannery.com", "myself only", []),  # myself only
          m(5, "Super Tannery India(Export House) Kanpur", None, "11-50", ["Consumer Services"]),
          m(6, "Publix Super Markets", "publix.com", "10001+", ["Retail"], conf=0.6)]
    assert [_ for _ in map(lambda x: x["company_data"]["crustdata_company_id"],
                           plausible(ms, Form(company_name="Super Tannery Ltd")))] == [1]
    assert len(plausible(ms, Form(company_name="Super Tannery Ltd", industry="leather"))) == 1
    two = [m(7, "Acme Leathers", "acme-a.example", "51-200", ["Leather Product Manufacturing"]),
           m(8, "Acme Leathers", "acme-b.example", "11-50", ["Leather Product Manufacturing"], conf=0.78)]
    assert len(plausible(two, Form(company_name="Acme Leathers"))) == 2


def test_enrich_news_adverse_needs_name_in_title():
    news = [{"article_title": "Fire breaks out at Super Tannery unit in Jajmau", "article_url": "https://n.example/1",
             "article_publish_date": "2026-10-01"},
            {"article_title": "SEBI imposes penalty on AKI India", "article_url": "https://n.example/2",
             "article_publish_date": "2026-07-02"},
            {"article_title": "Super Tannery Ltd Locks at Upper Circuit", "article_url": "https://n.example/3",
             "article_publish_date": "2026-10-13"}]
    fs = F.news_facts(news, "Super Tannery Limited", "2026-11-22T00:00:00+00:00")
    assert len(fs) == 1
    f = fs[0]
    assert f.value == {"type": "fire", "title": news[0]["article_title"], "date": "2026-10-01"}
    assert f.source.dated == "2026-10-01" and f.company_match == "company_id" and f.origin == "crustdata"


def test_revenue_estimate_becomes_a_sourced_turnover_fact():
    from invariant.evidence.facts import USD_INR, revenue_fact
    data = {"revenue": {"estimated": {"lower_bound_usd": 1_000_000, "upper_bound_usd": 5_000_000,
                                      "timeseries": [{"date": "2026-10-01"}, {"date": "2026-11-01"}]}}}
    f = revenue_fact(data, "2026-11-22T12:00:00+05:30")
    assert f.field == "turnover" and f.origin == "crustdata" and f.evidence_kind == "proxy_range"
    assert f.value == {"low": 1_000_000 * USD_INR, "high": 5_000_000 * USD_INR}
    assert f.source.dated == "2026-11-01" and "revenue.estimated" in f.source.quote
    assert revenue_fact({}, "2026-11-22T12:00:00+05:30") is None  # no revenue -> no fact, never a guess


def test_retail_page_does_not_beat_the_real_company_on_industry_fit():
    # live "Nike": ten 1.0 matches; a 2-10 person "Retail Apparel and Fashion" page with no domain
    # used to win because "apparel" counted as a manufacturing fit. Now: hold and ask.
    from invariant.evidence.resolve import plausible
    from invariant.shapes import Form

    def m(cid, name, domain, rng, inds):
        return {"confidence_score": 1.0, "company_data": {"crustdata_company_id": cid, "basic_info": {
            "name": name, "primary_domain": domain, "employee_count_range": rng, "industries": inds}}}
    matches = [m(1, "Nike", "nike.com", "10001+", ["Retail"]),
               m(2, "nike", None, "2-10", ["Retail Apparel and Fashion", "Retail"]),
               m(3, "NIKE", "nikemedics.it", "2-10", ["Medical Practices"])]
    form = Form(company_name="Nike", industry="footwear", countries=["Vietnam"])
    names = [((s["company_data"]["basic_info"]["primary_domain"]) or "") for s in plausible(matches, form)]
    assert "nike.com" in names and len(names) >= 2  # ambiguous -> the broker picks, never a guess


def test_remote_job_location_is_not_a_site():
    from invariant.evidence.facts import job_city
    assert job_city({"location": {"city": "Remote"}}) is None
    assert job_city({"location": {"raw": "Remote"}}) is None
    assert job_city({"location": {"city": "Unnao"}}) == "Unnao"


def test_news_review_explains_each_article_and_finds_undeclared_plants():
    from invariant.evidence.facts import review_news
    items = [
        {"title": "Kanpur Hide Exports opens new plant in Unnao", "url": "https://n.example/1", "date": "2026-09-01"},
        {"title": "Fire at Agra shoe market, 12 shops gutted", "url": "https://n.example/2"},
        {"title": "Kanpur Hide Exports posts record export growth", "url": "https://n.example/3"},
        {"title": "Kanpur Hide Exports factory in Kanpur expands", "url": "https://n.example/4"},
    ]
    facts, seen = review_news(items, "Kanpur Hide Exports Pvt Ltd", ["Kanpur"], None, linked=True,
                              origin="crustdata", what="POST /company/enrich -> news[].article_title",
                              fetched="2026-11-22T12:00:00+05:30")
    assert [(f.value, f.status, f.source.url) for f in facts] == [({"city": "Unnao"}, "undeclared", "https://n.example/1")]
    verdicts = {n.title: n.verdict for n in seen}
    assert verdicts["Kanpur Hide Exports opens new plant in Unnao"].startswith("Counted")
    assert verdicts["Fire at Agra shoe market, 12 shops gutted"].startswith("Ignored")  # does not name the company
    assert verdicts["Kanpur Hide Exports posts record export growth"].startswith("Read")
    assert verdicts["Kanpur Hide Exports factory in Kanpur expands"].startswith("Read")  # Kanpur already known
