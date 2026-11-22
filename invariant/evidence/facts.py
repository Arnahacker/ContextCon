"""Turn Crustdata / web / registry responses into sourced Facts. Pure functions: the caller
passes `fetched` (the only clock value) and the raw responses.

Fact ids: crustdata_<field>[_<n>], jobs_<field>_<n>, web_<field>_<n>, registry_<field>_<n>.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any, Iterable, Optional

from invariant.contracts import Resolution
from invariant.shapes import Fact, Form, Source

ENRICH_URL = "https://api.crustdata.com/company/enrich"
IDENTIFY_URL = "https://api.crustdata.com/company/identify"

HAZARD_KEYWORDS = ["boiler", "dyeing", "tannery", "tanning", "chrome", "chemical", "furnace", "night shift",
                   "welding", "solvent", "spray paint", "forklift"]
ADVERSE_TYPES = {  # event type -> words that signal it (title/snippet), whole-word match
    "fire": ["fire", "blaze", "gutted"],
    "explosion": ["explosion", "blast", "exploded"],
    "accident": ["accident", "injured", "killed", "death", "deaths"],
    "pollution": ["pollution", "effluent", "contamination"],
    "strike": ["strike", "lockout"],
    "court": ["court", "lawsuit", "tribunal", "ngt", "penalty", "raid", "raids"],
    "recall": ["recall"],
    "closure": ["closure", "shut down", "sealed", "closed down"],
}
# order matters: first hit wins
OCCUPANCY_KEYWORDS = [
    ("leather", ["leather", "tannery", "tanning"]),
    ("footwear", ["footwear", "shoe"]),
    ("garments", ["apparel", "garment", "fashion", "clothing"]),
    ("textiles", ["textile", "yarn", "spinning", "weaving"]),
    ("food_processing", ["food", "dairy", "beverage", "bakery"]),
    ("chemicals", ["chemical", "pharmaceutical", "plastics", "paint"]),
    ("engineering", ["engineering", "machinery", "automotive", "metal", "industrial automation"]),
    ("brassware", ["brass"]),
]
COMPANY_SUFFIXES = {"pvt", "private", "ltd", "limited", "co", "company", "inc", "llp", "corp", "corporation"}
INDIAN_STATES = {
    "andhra pradesh", "arunachal pradesh", "assam", "bihar", "chhattisgarh", "goa", "gujarat", "haryana",
    "himachal pradesh", "jharkhand", "karnataka", "kerala", "madhya pradesh", "maharashtra", "manipur",
    "meghalaya", "mizoram", "nagaland", "odisha", "punjab", "rajasthan", "sikkim", "tamil nadu", "telangana",
    "tripura", "uttar pradesh", "uttarakhand", "west bengal", "delhi", "jammu and kashmir", "ladakh",
    "puducherry", "chandigarh", "up", "tn",
}
COUNTRIES = {"india", "in", "ind", "united states", "usa", "us", "united kingdom", "uk"}


# ---------------------------------------------------------------- helpers


def norm(text: Optional[str]) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).split())


def norm_company(name: Optional[str]) -> str:
    words = norm(name).split()
    while words and words[-1] in COMPANY_SUFFIXES:
        words.pop()
    return " ".join(words)


def core_name(name: str) -> str:
    """Name without trailing legal suffixes, original case kept: "Vellore Tanners Ltd" -> "Vellore Tanners"."""
    words = (name or "").replace(".", " ").split()
    while len(words) > 1 and norm(words[-1]) in COMPANY_SUFFIXES:
        words.pop()
    return " ".join(words)


def contains_phrase(text: str, phrase: str) -> bool:
    """Whole-word phrase match on normalized text."""
    t, p = norm(text), norm(phrase)
    return bool(p) and re.search(rf"(?<![a-z0-9]){re.escape(p)}(?![a-z0-9])", t) is not None


def city_of(address: Any) -> Optional[str]:
    """City from an office address (dict with city, or a comma string). Address format is UNVERIFIED."""
    if isinstance(address, dict):
        return address.get("city") or address.get("locality")
    if not isinstance(address, str):
        return None
    parts = [p.strip() for p in address.split(",")]
    keep = [p for p in parts if p and not re.search(r"\d", p) and p.lower() not in INDIAN_STATES | COUNTRIES]
    return keep[-1] if keep else None


def job_city(job: dict) -> Optional[str]:
    loc = job.get("location") or {}
    return loc.get("city") or city_of(loc.get("raw"))


def office_cities(company_data: dict) -> list[str]:
    """Distinct office cities (headquarters first), case-insensitive dedupe, original spelling kept."""
    loc = company_data.get("locations") or {}
    raw = [loc.get("headquarters")] + list(loc.get("all_office_addresses") or [])
    seen: dict[str, str] = {}
    for a in raw:
        c = city_of(a)
        if c and norm(c) not in seen:
            seen[norm(c)] = c
    return list(seen.values())


def occupancy_of(industry: Optional[str], company_name: Optional[str]) -> Optional[str]:
    """One text -> one occupancy from the fixed list ("other" if nothing fits)."""
    if not industry:
        return None
    t = industry.lower()
    if "handicraft" in t:
        return "brassware" if "brass" in (company_name or "").lower() else "other"
    for occ, words in OCCUPANCY_KEYWORDS:
        if any(w in t for w in words):
            return occ
    return "other"


def occupancy_hints(texts: Iterable[Optional[str]], company_name: Optional[str]) -> list[str]:
    """Every occupancy any of the texts points to, in order, without "other"."""
    out: list[str] = []
    for t in texts:
        low = (t or "").lower()
        hits = [occ for occ, words in OCCUPANCY_KEYWORDS if any(w in low for w in words)]
        if "handicraft" in low and "brass" in (company_name or "").lower():
            hits.insert(0, "brassware")
        out += [h for h in hits if h not in out]
    return out


def _src(what, url, dated, fetched, quote) -> Source:
    return Source(what=what, url=url, dated=dated, fetched=fetched, quote=quote)


# ---------------------------------------------------------------- company + enrich


def company_fact(res: Resolution, fetched: str) -> Fact:
    return Fact(id="crustdata_company", field="company",
                value={"company_id": res.company_id, "name": res.name, "domain": res.domain},
                origin="crustdata", evidence_kind="direct", status="matches", company_match="company_id",
                source=_src("POST /company/identify -> matches[0].company_data.crustdata_company_id",
                            IDENTIFY_URL, None, fetched, f"crustdata_company_id: {res.company_id}"))


def enrich_facts(form: Form, company_data: dict, fetched: str) -> list[Fact]:
    facts: list[Fact] = []
    updated = company_data.get("updated_at")

    # headcount: one-directional lower bound
    hc = company_data.get("headcount") or {}
    total = hc.get("total")
    if isinstance(total, (int, float)):
        total = int(total)
        dates = [p.get("date") for p in hc.get("timeseries") or [] if p.get("date")]
        declared = form.declared_headcount
        if declared is None:
            status = "undeclared"
        elif total > declared * 1.25:
            status = "contradicts"
        elif total < declared:
            status = "consistent_unconfirmed"
        else:
            status = "matches"
        facts.append(Fact(id="crustdata_headcount", field="headcount", value=total, origin="crustdata",
                          evidence_kind="lower_bound", status=status, company_match="company_id",
                          source=_src("POST /company/enrich -> headcount.total", ENRICH_URL,
                                      max(dates) if dates else updated, fetched, f"headcount.total: {total}")))

    # sites: distinct office cities
    cities = office_cities(company_data)
    if cities:
        n, declared = len(cities), form.declared_sites
        if declared is None:
            status = "undeclared"
        elif n > declared:
            status = "contradicts"
        elif n == declared:
            status = "matches"
        else:
            status = "consistent_unconfirmed"
        quote = "locations: " + "; ".join(cities)
        what = "POST /company/enrich -> locations.headquarters + locations.all_office_addresses"
        facts.append(Fact(id="crustdata_sites", field="sites", value=n, origin="crustdata",
                          evidence_kind="lower_bound", status=status, company_match="company_id",
                          source=_src(what, ENRICH_URL, updated, fetched, quote)))
        if declared is not None and n > declared:
            mentioned = {norm(form.city)} if form.city else set()
            extra = [c for c in cities if norm(c) not in mentioned]
            for i, c in enumerate(extra, 1):
                facts.append(Fact(id=f"crustdata_sites_{i}", field="sites", value={"city": c}, origin="crustdata",
                                  evidence_kind="direct", status="undeclared", company_match="company_id",
                                  source=_src(what, ENRICH_URL, updated, fetched, f"office city: {c}")))

    # occupancy: taxonomy first, then description and name ("Manufacturing" alone says nothing)
    bi = company_data.get("basic_info") or {}
    tax = company_data.get("taxonomy") or {}
    name = bi.get("name") or form.company_name
    texts = [("taxonomy.professional_network_industry", tax.get("professional_network_industry"))]
    texts += [("taxonomy.professional_network_industries", t) for t in tax.get("professional_network_industries") or []]
    texts += [("basic_info.description", bi.get("description")), ("basic_info.name", bi.get("name"))]
    texts = [(k, t) for k, t in texts if t]
    if texts:
        hints = {}  # occupancy -> (field path, text) of the first text that points to it
        for k, t in texts:
            for occ in occupancy_hints([t], name):
                hints.setdefault(occ, (k, t))
        if not hints:
            occ, (k, t), status = "other", texts[0], ("undeclared" if not form.industry else "consistent_unconfirmed")
        elif not form.industry:
            occ = next(iter(hints))
            (k, t), status = hints[occ], "undeclared"
        elif form.industry in hints:
            occ, (k, t), status = form.industry, hints[form.industry], "matches"
        else:
            occ = next(iter(hints))
            (k, t), status = hints[occ], "contradicts"
        kind = "direct" if k.startswith("taxonomy") and occ != "other" else "proxy_range"
        facts.append(Fact(id="crustdata_occupancy", field="occupancy", value=occ, origin="crustdata",
                          evidence_kind=kind, status=status, company_match="company_id",
                          source=_src(f"POST /company/enrich -> {k}", ENRICH_URL, updated, fetched, f"{k}: {t}")))
    # export_countries: no unambiguous field in enrich -> no fact (decide handles the gap)
    return facts


# ---------------------------------------------------------------- jobs


def job_facts(form: Form, job_listings: Iterable[dict], known_cities: Iterable[str], fetched: str,
              since: Optional[str] = None) -> list[Fact]:
    """Hazard keywords in job titles not covered by the declared activities, and job cities
    that are neither declared nor known offices. `since` = ISO date cutoff (inclusive)."""
    activities = " ".join(form.activities).lower()
    known = {norm(c) for c in known_cities} | ({norm(form.city)} if form.city else set())
    facts: list[Fact] = []
    hz, st = 0, 0
    new_cities: set[str] = set()
    for job in job_listings:
        jd = job.get("job_details") or {}
        title, url = jd.get("title") or "", jd.get("url")
        dated = (job.get("metadata") or {}).get("date_added")
        if since and dated and str(dated)[:10] < since:
            continue
        kw = next((k for k in HAZARD_KEYWORDS if contains_phrase(title, k) and k not in activities), None)
        if kw:
            hz += 1
            facts.append(Fact(id=f"jobs_hazardous_activity_{hz}", field="hazardous_activity",
                              value={"activity": kw, "job_title": title}, origin="crustdata",
                              evidence_kind="direct", status="undeclared", company_match="company_id",
                              source=_src("POST /job/search -> job_details.title", url, dated, fetched,
                                          f"job_details.title: {title}")))
        city = job_city(job)
        if city and norm(city) not in known and norm(city) not in new_cities:
            new_cities.add(norm(city))
            st += 1
            facts.append(Fact(id=f"jobs_sites_{st}", field="sites", value={"city": city}, origin="crustdata",
                              evidence_kind="direct", status="undeclared", company_match="company_id",
                              source=_src("POST /job/search -> location", url, dated, fetched,
                                          f"location.raw: {(job.get('location') or {}).get('raw') or city}")))
    return facts


# ---------------------------------------------------------------- web news


def adverse_type(text: str) -> Optional[str]:
    for t, words in ADVERSE_TYPES.items():
        if any(contains_phrase(text, w) for w in words):
            return t
    return None


def names_company(text: str, company_name: str, cities: Iterable[str], domain: Optional[str]) -> Optional[str]:
    """Rule 6: the result must name the company AND (a city or the domain).
    Returns the company_match ("domain" / "name_city") or None to drop the result."""
    core = norm_company(company_name)
    if not contains_phrase(text, core):
        return None
    # the city must appear outside the name itself ("Vellore Tanners" does not prove "Vellore")
    if domain and domain.lower() in (text or "").lower():
        return "domain"
    text = re.sub(rf"(?<![a-z0-9]){re.escape(core)}(?![a-z0-9])", " ", norm(text))
    if any(contains_phrase(text, c) for c in cities if c):
        return "name_city"
    return None


class _MetaDates(HTMLParser):
    KEYS = ("article:published_time", "datepublished", "date", "publish-date", "pubdate", "og:published_time")

    def __init__(self):
        super().__init__()
        self.found: dict[str, str] = {}

    def handle_starttag(self, tag, attrs):
        if tag != "meta":
            return
        a = {k.lower(): (v or "") for k, v in attrs}
        key = (a.get("property") or a.get("name") or a.get("itemprop") or "").lower()
        if key in self.KEYS and a.get("content"):
            self.found.setdefault(key, a["content"])


def publish_date(html: Optional[str]) -> Optional[str]:
    """Publish date (YYYY-MM-DD) from article meta tags / JSON-LD, else None. Never invented."""
    if not html:
        return None
    p = _MetaDates()
    try:
        p.feed(html)
    except Exception:
        pass
    candidates = [p.found[k] for k in _MetaDates.KEYS if k in p.found]
    m = re.search(r'"datePublished"\s*:\s*"([^"]+)"', html)
    if m:
        candidates.append(m.group(1))
    for c in candidates:
        d = re.match(r"(\d{4}-\d{2}-\d{2})", c.strip())
        if d:
            return d.group(1)
    return None


def adverse_facts(results: Iterable[dict], company_name: str, cities: Iterable[str], domain: Optional[str],
                  dates: dict[str, Optional[str]], fetched: str) -> list[Fact]:
    facts: list[Fact] = []
    cities = list(cities)
    for r in results:
        title, snippet, url = r.get("title") or "", r.get("snippet") or "", r.get("url")
        text = f"{title} {snippet}"
        match = names_company(text, company_name, cities, domain)
        kind = adverse_type(text)
        if not match or not kind:
            continue
        date = dates.get(url)
        facts.append(Fact(id=f"web_adverse_event_{len(facts) + 1}", field="adverse_event",
                          value={"type": kind, "title": title, "date": date}, origin="web",
                          evidence_kind="direct", status="undeclared", company_match=match,
                          source=_src("POST /web/search/live -> results[].title", url, date, fetched,
                                      f"title: {title}")))
    return facts


def news_facts(news: Iterable[dict], company_name: str, fetched: str) -> list[Fact]:
    """Adverse items from enrich news[] (dated, already linked to the company id by Crustdata).
    Counts only when the title itself names the company."""
    facts: list[Fact] = []
    core = norm_company(company_name)
    for n in news or []:
        title = n.get("article_title") or ""
        kind = adverse_type(title)
        if not kind or not contains_phrase(title, core):
            continue
        date = n.get("article_publish_date")
        date = date[:10] if isinstance(date, str) and re.match(r"\d{4}-\d{2}-\d{2}", date) else None
        facts.append(Fact(id=f"crustdata_adverse_event_{len(facts) + 1}", field="adverse_event",
                          value={"type": kind, "title": title, "date": date}, origin="crustdata",
                          evidence_kind="direct", status="undeclared", company_match="company_id",
                          source=_src("POST /company/enrich -> news[].article_title", n.get("article_url"),
                                      date, fetched, f"article_title: {title}")))
    return facts


def adverse_candidates(results: Iterable[dict], company_name: str, cities: Iterable[str],
                       domain: Optional[str]) -> list[str]:
    """URLs of results that will become facts (so only those get a /web/enrich/live date lookup)."""
    cities = list(cities)
    out = []
    for r in results:
        text = f"{r.get('title') or ''} {r.get('snippet') or ''}"
        if r.get("url") and names_company(text, company_name, cities, domain) and adverse_type(text):
            out.append(r["url"])
    return out


# ---------------------------------------------------------------- sanctions


def sanctions_facts(response: dict, fetched: str) -> list[Fact]:
    results = ((response.get("responses") or {}).get("q") or {}).get("results") or []
    facts = []
    for r in results:
        if not r.get("match"):
            continue
        facts.append(Fact(id=f"registry_sanctions_{len(facts) + 1}", field="sanctions",
                          value={"match": True, "caption": r.get("caption"), "score": r.get("score"),
                                 "datasets": r.get("datasets") or []},
                          origin="registry", evidence_kind="direct", status="contradicts",
                          company_match="name_city",
                          source=_src("POST opensanctions /match/default -> responses.q.results[]",
                                      f"https://www.opensanctions.org/entities/{r.get('id')}/", None, fetched,
                                      f"caption: {r.get('caption')} (score {r.get('score')})")))
    return facts
