"""Unwrap the real Crustdata v2 response shape.

Verified against a live /company/enrich call on 2026-11-22. The envelope is:

  [ {matched_on, match_type, matches: [ {confidence_score, company_data: {...}} ]} ]

a LIST at the top level - not {"companies": [...]}. Everything useful hangs off
company_data, nested by section: basic_info / headcount / locations / taxonomy.
"""
from __future__ import annotations
import re
from typing import Any, Optional

# certifications that are worth money, and how they appear in free text
CERT_PATTERNS = {
    "ISO_45001": r"\biso[\s\-]?45001\b",
    "ISO_14001": r"\biso[\s\-]?14001\b",
    "LWG_AUDIT": r"\bleather working group\b|\blwg\b",
    "SA8000":    r"\bsa[\s\-]?8000\b",
    "BSCI":      r"\bbsci\b",
    "WRAP":      r"\bwrap\b",
}

# region keys in headcount.by_region_absolute that are rollups, not sites
ROLLUP = re.compile(r"^(india|united states|usa|uk|united kingdom|europe)$", re.I)


def matches(resp: Any) -> list[dict]:
    """Every match from an identify or enrich response, best confidence first."""
    out = []
    if isinstance(resp, dict):          # some clients wrap it
        resp = resp.get("data") or resp.get("results") or [resp]
    for group in resp or []:
        if not isinstance(group, dict):
            continue
        for m in group.get("matches") or []:
            cd = m.get("company_data") or {}
            out.append({"confidence": m.get("confidence_score") or 0.0,
                        "matched_on": group.get("matched_on"),
                        "data": cd})
    out.sort(key=lambda x: -x["confidence"])
    return out


def basic(cd: dict) -> dict:
    return cd.get("basic_info") or {}


def company_id(cd: dict) -> Optional[int]:
    return cd.get("crustdata_company_id") or basic(cd).get("crustdata_company_id")


def name(cd: dict) -> Optional[str]:
    return basic(cd).get("name")


def domain(cd: dict) -> Optional[str]:
    return basic(cd).get("primary_domain")


def profile_url(cd: dict) -> Optional[str]:
    """Something a human can actually click to check the claim."""
    b = basic(cd)
    return (b.get("professional_network_url") or b.get("website")
            or (f"https://{b['primary_domain']}" if b.get("primary_domain") else None))


def year_founded(cd: dict) -> Optional[int]:
    return basic(cd).get("year_founded")


def employee_range(cd: dict) -> Optional[str]:
    return basic(cd).get("employee_count_range")


def specialities(cd: dict) -> list[str]:
    return (cd.get("taxonomy") or {}).get("professional_network_specialities") or []


def role_mix(cd: dict, top: int = 6) -> dict[str, int]:
    raw = (cd.get("headcount") or {}).get("by_role_absolute") or {}
    return dict(sorted(raw.items(), key=lambda x: -x[1])[:top])


def hq(cd: dict) -> Optional[str]:
    loc = cd.get("locations") or {}
    bits = [loc.get("city"), loc.get("state")]
    s = ", ".join(b for b in bits if b)
    return s or (loc.get("headquarters") or "").split(",")[0] or None


def headcount_total(cd: dict) -> Optional[int]:
    return (cd.get("headcount") or {}).get("total")


def headcount_dated(cd: dict) -> Optional[str]:
    ts = (cd.get("headcount") or {}).get("timeseries") or []
    return ts[-1].get("date") if ts else None


def growth_yoy_pct(cd: dict) -> Optional[float]:
    """Crustdata computes this for us. Do not recompute it from the timeseries."""
    g = (cd.get("headcount") or {}).get("growth_percent") or {}
    v = g.get("yoy")
    return round(v, 1) if isinstance(v, (int, float)) else None


def sites(cd: dict) -> list[str]:
    """Distinct PREMISES, from the address list only.

    Deliberately NOT derived from headcount.by_region_absolute. Those keys come
    at several granularities for the same place ("Greater Kolkata Area",
    "Rajarhat", "West Bengal, India" are one location described three ways), so
    counting them would invent undeclared sites that do not exist. A wrong fact
    costs more than a missed one. Employee regions are reported as context
    instead - see employee_regions() and offshore_regions().
    """
    loc = cd.get("locations") or {}
    out: list[str] = []

    def add(label: Optional[str]):
        if not label:
            return
        label = str(label).strip().rstrip(",")
        if label and label.lower() not in {o.lower() for o in out}:
            out.append(label)

    add(loc.get("city"))
    for addr in loc.get("all_office_addresses") or []:
        parts = [p.strip() for p in str(addr).split(",") if p.strip()]
        # ..., City, State, PIN, Country  -> the city is 4th from the end
        if len(parts) >= 4:
            add(parts[-4])
        elif parts:
            add(parts[0])
    return out


def employee_regions(cd: dict, min_staff: int = 2) -> dict[str, int]:
    """Where staff actually sit. CONTEXT, not a site count: the keys overlap."""
    raw = (cd.get("headcount") or {}).get("by_region_absolute") or {}
    return {k: v for k, v in sorted(raw.items(), key=lambda x: -x[1])
            if v >= min_staff and not ROLLUP.match(k.strip())}


# Conservative by design: a region counts as offshore only if it IS a country
# we recognise. Guessing from place-name patterns called Rajarhat and
# Budge Budge-I (both West Bengal) "offshore". Under-reporting is acceptable;
# inventing a fact is not.
COUNTRIES = {
 "afghanistan","albania","algeria","argentina","armenia","australia","austria",
 "bahrain","bangladesh","belarus","belgium","bhutan","bolivia","brazil","bulgaria",
 "cambodia","canada","chile","china","colombia","croatia","cuba","cyprus","czechia",
 "czech republic","denmark","ecuador","egypt","estonia","ethiopia","finland","france",
 "georgia","germany","ghana","greece","hong kong","hungary","iceland","indonesia",
 "iran","iraq","ireland","israel","italy","japan","jordan","kazakhstan","kenya",
 "kuwait","latvia","lebanon","lithuania","luxembourg","malaysia","maldives","mexico",
 "morocco","myanmar","nepal","netherlands","new zealand","nigeria","norway","oman",
 "pakistan","peru","philippines","poland","portugal","qatar","romania","russia",
 "saudi arabia","serbia","singapore","slovakia","slovenia","south africa","south korea",
 "korea","spain","sri lanka","sweden","switzerland","taiwan","tanzania","thailand",
 "tunisia","turkey","uganda","ukraine","united arab emirates","uae","united kingdom",
 "uk","england","scotland","united states","usa","united states of america","uruguay",
 "uzbekistan","vietnam","yemen","zambia","zimbabwe",
}


def offshore_regions(cd: dict) -> dict[str, int]:
    """Staff in a country other than the home country.

    Only fires on a recognised country name, so it can miss a site but can
    never invent one. An exporter with people sitting in Italy is a real
    exposure the form did not mention.
    """
    loc = cd.get("locations") or {}
    home = (loc.get("country") or
            (cd.get("headcount") or {}).get("largest_headcount_country") or "")
    home_names = {"india", "ind", "in"} if home.upper().startswith("IN") else {home.lower()}
    out = {}
    for k, v in ((cd.get("headcount") or {}).get("by_region_absolute") or {}).items():
        key = k.strip().lower()
        tail = key.split(",")[-1].strip()
        for cand in (key, tail):
            if cand in COUNTRIES and cand not in home_names:
                out[k.strip()] = v
                break
    return out


def industry(cd: dict) -> Optional[str]:
    return (cd.get("taxonomy") or {}).get("professional_network_industry")


def activity_text(cd: dict) -> str:
    """Everything the company says about what it does, for hazard matching."""
    tax = cd.get("taxonomy") or {}
    bits = [basic(cd).get("description") or "",
            industry(cd) or "",
            " ".join(tax.get("professional_network_specialities") or []),
            " ".join(tax.get("categories") or [])]
    return " ".join(bits)


def certifications(cd: dict) -> list[tuple[str, str]]:
    """(code, the sentence that proves it) found in the company's own description.

    This is free: the description already comes back with basic_info, so you get
    the discount evidence without scraping anything.
    """
    text = basic(cd).get("description") or ""
    found = []
    for code, pat in CERT_PATTERNS.items():
        m = re.search(pat, text, re.I)
        if m:
            start = max(0, m.start() - 90)
            found.append((code, text[start:m.end() + 40].strip()))
    return found


# ---------------------------------------------------------------- /job/search
# Verified live 2026-11-22. Envelope is a DICT, not the identify/enrich list:
#   {job_listings: [...], next_cursor, total_count}
# each listing: job_details.{title,url,workplace_type,...}, location.{raw,city,
# state,country}, content.description, metadata.date_added,
# company.basic_info.crustdata_company_id.
# The filter field is company.basic_info.crustdata_company_id - "company_id" is
# rejected with HTTP 400, and a fuzzy (.) match on company.basic_info.name
# returned OTHER companies' jobs. Always filter by id, and check it again here.

def jobs(resp: Any, company_id: Optional[int] = None) -> list[dict]:
    """Flat {title, description, url, posted, location, city, country, remote}.

    Listings that belong to a different company are dropped: a job at a
    lookalike must never become a hazard or a site of this applicant.
    """
    out = []
    if not isinstance(resp, dict):
        return out
    for j in resp.get("job_listings") or []:
        if not isinstance(j, dict):
            continue
        jd = j.get("job_details") or {}
        loc = j.get("location") or {}
        owner = ((j.get("company") or {}).get("basic_info") or {}).get("crustdata_company_id")
        # unknown owner is dropped too: one live listing came back with a null
        # id and a scraped job title as its company name
        if company_id is not None and (owner is None or int(owner) != int(company_id)):
            continue
        added = (j.get("metadata") or {}).get("date_added") or ""
        out.append({
            "title": jd.get("title") or "",
            "description": (j.get("content") or {}).get("description") or "",
            "url": jd.get("url"),
            "posted": added[:10] or None,
            "location": loc.get("raw") or "",
            "city": loc.get("city"),
            "country": loc.get("country"),
            "remote": (jd.get("workplace_type") or "").lower() == "remote",
        })
    return out


def jobs_total(resp: Any) -> Optional[int]:
    return resp.get("total_count") if isinstance(resp, dict) else None


# ----------------------------------------------------------- /web/search/live
# Verified live 2026-11-22:
#   {success, query, timestamp (ms), results: [...], metadata: {total_results,
#    empty_pages, failed_pages}}
# each web result: {position, title, snippet, url, source}. There is NO date
# field, and url is often a google.com/goto redirect rather than the page.

def web_ok(resp: Any) -> bool:
    """False means the search did not complete - that is cannot_verify, not
    'nothing found'."""
    if not isinstance(resp, dict) or resp.get("success") is False:
        return False
    return not (resp.get("metadata") or {}).get("failed_pages")


def web_results(resp: Any) -> list[dict]:
    out = []
    if not isinstance(resp, dict):
        return out
    for r in resp.get("results") or []:
        if isinstance(r, dict):
            out.append({"title": r.get("title") or "", "snippet": r.get("snippet") or "",
                        "url": r.get("url"), "date": r.get("date"),
                        "source": r.get("source")})
    return out
