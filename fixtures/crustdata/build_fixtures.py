"""Regenerate fixtures/crustdata/ (readable response files + index.json) for the cases in
tests/cases/cases.json and the real demo company (Super Tannery, from live_samples/).
Run: conda run -n invariant python fixtures/crustdata/build_fixtures.py
To add a company: add a company(...) call below (or hand-write a file + index entry) and rerun."""
import json, shutil, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]; sys.path.insert(0, str(ROOT))
from invariant.evidence.gather import enrich_body, jobs_body, news_body, web_enrich_body

FX = ROOT / "fixtures" / "crustdata"
LIVE = FX / "live_samples"
GENERATED = ["company_identify", "company_enrich", "job_search", "web_search_live", "web_enrich_live"]
for d in GENERATED:
    shutil.rmtree(FX / d, ignore_errors=True)
entries = []

def put(endpoint, body, rel, response):
    p = FX / rel; p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(response, indent=2, ensure_ascii=False) + "\n")
    entries.append({"endpoint": endpoint, "body": body, "response": rel})

def basic(cid, name, domain, rng, industry, desc=None):
    return {"name": name, "crustdata_company_id": cid, "description": desc or f"{name} is a {industry.lower()} company based out of India.", "primary_domain": domain, "employee_count_range": rng, "industries": [industry],
            "website": f"https://{domain}", "professional_network_url": f"https://www.linkedin.com/company/{domain.split('.')[0]}",
            "year_founded": 2004, "company_type": "Privately Held", "industries": [industry, "Manufacturing"]}

def series(total):
    return [{"date": "2026-08-01", "employee_count": total - 6}, {"date": "2026-09-01", "employee_count": total - 2},
            {"date": "2026-10-01", "employee_count": total}]

def company(slug, cid, name, domain, rng, industry, hc, hq, offices, jobs, news, conf=0.95, extra_match=None,
            form_name=None, by_domain=False, desc=None, enrich_news=()):
    b = basic(cid, name, domain, rng, industry, desc)
    match = {"confidence_score": conf, "company_data": {"crustdata_company_id": cid, "basic_info": b}}
    matches = [match] + ([extra_match] if extra_match else [])
    if by_domain:
        put("/company/identify", {"domains": [domain]}, f"company_identify/{slug}_domain.json",
            [{"matched_on": domain, "match_type": "domain", "matches": [dict(match, confidence_score=1.0)]}])
    else:
        put("/company/identify", {"names": [form_name or name]}, f"company_identify/{slug}.json",
            [{"matched_on": form_name or name, "match_type": "name", "matches": matches}])
    cd = {"crustdata_company_id": cid, "basic_info": b,
          "headcount": {"total": hc, "timeseries": series(hc), "growth_percent": {"mom": 1.3, "qoq": 4.0, "six_months": 6.1, "yoy": 9.5},
                        "largest_headcount_country": "IND", "by_region_absolute": {"India": hc}},
          "locations": {"country": "IND", "state": hq.split(", ")[1], "headquarters": hq, "street_address": None,
                        "all_office_addresses": offices},
          "taxonomy": {"professional_network_industry": industry, "professional_network_industries": [industry],
                       "categories": [], "primary_naics_detail": None},
          "news": list(enrich_news),
          "updated_at": "2026-11-01T00:00:00Z", "indexed_at": "2026-11-01T00:00:00Z"}
    put("/company/enrich", enrich_body(str(cid)), f"company_enrich/{slug}.json",
        [{"matched_on": str(cid), "match_type": "crustdata_company_id", "matches": [{"confidence_score": 1, "company_data": cd}]}])
    listings = [{"job_details": {"title": t, "url": f"https://jobs.example/{slug}/{i}"},
                 "location": {"raw": f"{c}, {hq.split(', ')[1]}", "city": c},
                 "metadata": {"date_added": d}} for i, (t, c, d) in enumerate(jobs, 1)]
    put("/job/search", jobs_body(domain), f"job_search/{slug}.json",
        {"job_listings": listings, "next_cursor": None, "total_count": len(listings)})
    city = hq.split(",")[0]  # = form.city for the named cases, HQ city when picked by domain
    q = news_body(name, city)
    put("/web/search/live", q, f"web_search_live/{slug}.json",
        {"success": True, "query": q["query"], "timestamp": 1795334400000,
         "results": [dict(r, position=i) for i, r in enumerate(news, 1)], "metadata": {"total_results": len(news)}})

# 1 hero (also 8)
company("kanpur_hide", 700101, "Kanpur Hide Exports Pvt Ltd", "kanpurhide.example", "201-500", "Leather", 310,
        "Kanpur, Uttar Pradesh, India",
        ["Plot 14, Dada Nagar Industrial Area, Kanpur, Uttar Pradesh 208022, India", "Unnao, Uttar Pradesh, India",
         "Kanpur Dehat, Uttar Pradesh, India", "Guindy, Chennai, Tamil Nadu 600032, India"],
        [("Tannery Operator - Unnao", "Unnao", "2026-10-02"), ("Chrome Tanning Supervisor", "Kanpur", "2026-09-15"),
         ("Export Documentation Executive", "Kanpur", "2026-08-20")], [],
        extra_match={"confidence_score": 0.42, "company_data": {"crustdata_company_id": 700191,
                     "basic_info": basic(700191, "Kanpur Hides & Skins Traders", "kanpurhides-traders.example", "1-10", "Wholesale")}})
# 2 clean (also 6, 9, 10)
company("agra_footwear", 700102, "Agra Footwear Works", "agrafootwear.example", "51-200", "Footwear", 80,
        "Agra, Uttar Pradesh, India", ["Sikandra Industrial Area, Agra, Uttar Pradesh 282007, India"],
        [("Shoe Upper Stitcher", "Agra", "2026-10-10"), ("Quality Checker", "Agra", "2026-09-01")],
        [{"source": "news", "title": "Fire at Agra shoe market, 12 shops gutted", "url": "https://news.example/agra-shoe-market-fire",
          "snippet": "A fire broke out in the Hing Ki Mandi shoe market in Agra on Sunday night."}])
# 3 hidden hazard
company("stitchline", 700103, "Tiruppur Stitchline Garments", "stitchline.example", "201-500", "Apparel & Fashion", 210,
        "Tiruppur, Tamil Nadu, India", [],
        [("Boiler Operator (Night Shift)", "Tiruppur", "2026-10-20"), ("Dyeing Machine Operator", "Tiruppur", "2026-09-28"),
         ("Tailor", "Tiruppur", "2026-09-05")], [])
# 4 bad news
company("vellore_tanners", 700104, "Vellore Tanners Ltd", "velloretanners.example", "51-200", "Leather", 160,
        "Ranipet, Tamil Nadu, India", ["SIPCOT Industrial Complex, Ranipet, Tamil Nadu 632403, India", "Vellore, Tamil Nadu, India"], [],
        [{"source": "news", "title": "Major fire at Vellore Tanners unit in Ranipet", "url": "https://news.example/tn/vellore-tanners-ranipet-fire",
          "snippet": "A major fire broke out at the Vellore Tanners Ltd tannery in the SIPCOT complex, Ranipet; no casualties were reported."},
         {"source": "news", "title": "Vellore Tannery Workers Cooperative hit by fire in Ambur", "url": "https://news.example/tn/ambur-coop-fire",
          "snippet": "Fire damaged stock at a workers' cooperative tannery in Ambur."},
         {"source": "web", "title": "Vellore Tanners Association threatens strike over effluent charges", "url": "https://news.example/tn/tanners-association-strike",
          "snippet": "The district tanners association said members may strike next month."}])
put("/web/enrich/live", web_enrich_body(["https://news.example/tn/vellore-tanners-ranipet-fire"]), "web_enrich_live/vellore_tanners_fire.json",
    [{"success": True, "url": "https://news.example/tn/vellore-tanners-ranipet-fire", "timestamp": 1795334400000,
      "title": "Major fire at Vellore Tanners unit in Ranipet",
      "content": "<!DOCTYPE html><html><head><title>Major fire at Vellore Tanners unit in Ranipet</title>"
                 "<meta property=\"article:published_time\" content=\"2026-10-14T08:30:00+05:30\"/>"
                 "<meta property=\"og:title\" content=\"Major fire at Vellore Tanners unit in Ranipet\"/></head>"
                 "<body><article><h1>Major fire at Vellore Tanners unit in Ranipet</h1><p>A major fire broke out at the Vellore Tanners Ltd tannery in the SIPCOT complex, Ranipet.</p></article></body></html>"}])
# 5 lookalike: two plausible companies tied by name -> ambiguous. Each is also fixtured by domain
# (the broker picks one -> case layer re-gathers with form.domain set).
def bal(cid, dom, conf, where):
    return {"confidence_score": conf, "company_data": {"crustdata_company_id": cid,
            "basic_info": basic(cid, "Shree Balaji Exports", dom, "51-200", "Textiles",
                                f"Shree Balaji Exports is a textiles company based out of {where}, India.")}}
put("/company/identify", {"names": ["Shree Balaji Exports"]}, "company_identify/shree_balaji.json",
    [{"matched_on": "Shree Balaji Exports", "match_type": "name",
      "matches": [bal(700105, "balajijaipur.example", 0.81, "Jaipur, Rajasthan"),
                  bal(700106, "balajisurat.example", 0.79, "Surat, Gujarat"),
                  {"confidence_score": 0.8, "company_data": {"crustdata_company_id": 700195, "basic_info": {
                      "name": "SHREE BALAJI EXPORTS (U.K.) LIMITED", "primary_domain": None, "employee_count_range": None,
                      "industries": ["Textile Manufacturing"], "description": "A textiles company based out of United Kingdom."}}}]}])
company("balaji_jaipur", 700105, "Shree Balaji Exports", "balajijaipur.example", "51-200", "Textiles", 70,
        "Jaipur, Rajasthan, India", [], [("Dyeing Master", "Jaipur", "2026-10-01")], [], by_domain=True)
company("balaji_surat", 700106, "Shree Balaji Exports", "balajisurat.example", "51-200", "Textiles", 55,
        "Surat, Gujarat, India", [], [("Weaving Supervisor", "Surat", "2026-10-03")], [], by_domain=True)
# 7 nobody can answer
company("moradabad_brass", 700107, "Moradabad Brassware Co", "moradabadbrass.example", "11-50", "Handicrafts", 40,
        "Moradabad, Uttar Pradesh, India", [], [], [])

# Real demo company: Super Tannery Limited (id 4889), straight from live_samples/
ident = json.loads((LIVE / "identify_15_leather_names.json").read_text())
st_ident = next(x for x in ident if x["matched_on"] == "Super Tannery")
for n in ["Super Tannery Ltd", "Super Tannery Limited", "Super Tannery"]:
    put("/company/identify", {"names": [n]}, "company_identify/super_tannery.json", [st_ident])
st_match = next(m for m in st_ident["matches"] if m["company_data"]["crustdata_company_id"] == 4889)
put("/company/identify", {"domains": ["supertannery.com"]}, "company_identify/super_tannery_domain.json",
    [{"matched_on": "supertannery.com", "match_type": "domain", "matches": [dict(st_match, confidence_score=1.0)]}])
enr = json.loads((LIVE / "enrich_4889_15909978_26702196_16737194.json").read_text())
put("/company/enrich", enrich_body("4889"), "company_enrich/super_tannery.json",
    [next(x for x in enr if x["matched_on"] == "4889")])
put("/job/search", jobs_body("supertannery.com"), "job_search/super_tannery.json",
    json.loads((LIVE / "jobs_domain_supertannery.com.json").read_text()))

(FX / "index.json").write_text(json.dumps({
    "_note": "Offline fixtures. Each entry: endpoint + request body (matched ignoring key order, case and extra spaces) -> response file. "
             "A file at <endpoint_slug>/<request_hash>.json is also found without an index entry.",
    "entries": entries}, indent=2, ensure_ascii=False) + "\n")
print(len(entries), "entries")
