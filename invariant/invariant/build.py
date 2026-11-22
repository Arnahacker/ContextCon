"""Turn API responses into Facts. Every fact gets a source or it is not created."""
from __future__ import annotations
import re
from typing import Any, Optional

from .facts import (Fact, Source, MATCHES, CONTRADICTS, CONSISTENT_UNCONFIRMED,
                    CANNOT_VERIFY, UNDECLARED, DIRECT, LOWER_BOUND, SEARCH_NEGATIVE,
                    PROXY_RANGE)
from .normalize import to_occupancy, canonical_name

# job-title words -> the hazardous process they reveal. Fire-relevant only.
HAZARD_WORDS = {
    "tannery": "tanning", "tanning": "tanning", "chrome": "chrome tanning",
    "boiler": "boiler operation", "dyeing": "dyeing", "dye house": "dyeing",
    "effluent": "effluent treatment", "chemical": "chemical handling",
    "welding": "hot work", "welder": "hot work", "furnace": "furnace",
    "foundry": "molten metal", "forging": "forging", "spray paint": "spray painting",
    "paint shop": "spray painting", "solvent": "solvent handling",
    "ammonia": "ammonia refrigeration", "lpg": "LPG handling",
    "kiln": "kiln firing", "electroplating": "electroplating",
    "night shift": "night shift working",
}


def declared_facts(form) -> list[Fact]:
    out = []
    if form.declared_headcount is not None:
        out.append(Fact("h_declared", "headcount", form.declared_headcount, "declared",
                        MATCHES, DIRECT, None,
                        Source(what="applicant statement",
                               quote=f"{form.declared_headcount} employees")))
    if form.declared_sites is not None:
        out.append(Fact("s_declared", "sites", form.declared_sites, "declared",
                        MATCHES, DIRECT, None,
                        Source(what="applicant statement",
                               quote=f"{form.declared_sites} units")))
    if form.sum_insured_inr:
        out.append(Fact("si_declared", "sum_insured_inr", form.sum_insured_inr,
                        "declared", MATCHES, DIRECT, None,
                        Source(what="applicant statement")))
    if form.cover_type:
        out.append(Fact("cov_declared", "cover_type", form.cover_type, "declared",
                        MATCHES, DIRECT, None, Source(what="applicant statement")))
    occ = to_occupancy(form.industry, form.activities)
    if occ != "unknown":
        out.append(Fact("occ_declared", "occupancy", occ, "declared", MATCHES, DIRECT,
                        None, Source(what="applicant statement",
                                     quote=form.industry or "")))
    return out


def headcount_facts(declared: Optional[int], record: Optional[int],
                    tolerance_pct: float, src: Source) -> list[Fact]:
    """ONE-DIRECTIONAL. Public profiles undercount factory floors.

    record far ABOVE declared  -> contradicts (they understated)
    record at or BELOW declared -> consistent_unconfirmed, never a mismatch
    """
    if record is None:
        return [Fact("h_record", "headcount", None, "crustdata", CANNOT_VERIFY,
                     note="no headcount in the record")]
    if declared is None:
        return [Fact("h_record", "headcount", record, "crustdata",
                     CONSISTENT_UNCONFIRMED, LOWER_BOUND, "company_id", src)]
    limit = declared * (1 + tolerance_pct / 100.0)
    status = CONTRADICTS if record > limit else CONSISTENT_UNCONFIRMED
    note = (f"record {record} is more than {tolerance_pct:.0f}% above declared {declared}"
            if status == CONTRADICTS else
            f"record {record} does not exceed declared {declared} by more than "
            f"{tolerance_pct:.0f}%; public profiles undercount factory staff")
    return [Fact("h_record", "headcount", record, "crustdata", status,
                 LOWER_BOUND, "company_id", src, note=note)]


def site_facts(declared_sites, locations: list[dict], src_what: str,
               url: str | None = None) -> list[Fact]:
    out: list[Fact] = []
    if not locations:
        return out
    seen = []
    for loc in locations:
        label = ", ".join(x for x in (loc.get("city"), loc.get("state")) if x)
        if label and label not in seen:
            seen.append(label)
    out.append(Fact("sites_record", "sites", len(seen), "crustdata",
                    CONTRADICTS if (declared_sites and len(seen) > declared_sites)
                    else CONSISTENT_UNCONFIRMED,
                    DIRECT, "company_id",
                    Source(what=src_what, url=url, quote="; ".join(seen))))
    if declared_sites and len(seen) > declared_sites:
        for extra in seen[declared_sites:]:
            out.append(Fact(f"site_extra_{extra[:12].replace(' ','_')}",
                            "undeclared_site", extra, "crustdata", UNDECLARED,
                            DIRECT, "company_id",
                            Source(what=src_what, url=url, quote=extra)))
    return out


def hazard_facts(jobs: list[dict], declared_activities: list[str],
                 src_what: str = "POST /job/search -> job_listings[].job_details.title"
                 ) -> list[Fact]:
    """Hazardous work shows up in hiring long before it shows up on a form.

    `jobs` is adapt.jobs() output. Matched on the TITLE only: real descriptions
    are 1000+ words of boilerplate, and "chemical" in a benefits blurb is not a
    process on the floor. A wrong fact costs more than a missed one.
    """
    out, seen = [], set()
    blob = " ".join(declared_activities or []).lower()
    for j in jobs:
        text = (j.get("title") or "").lower()
        for needle, label in HAZARD_WORDS.items():
            if needle in text and label not in seen and needle not in blob:
                seen.add(label)
                out.append(Fact(f"haz_{label.replace(' ','_')}", "undeclared_hazard",
                                label, "crustdata", UNDECLARED, DIRECT, "company_id",
                                Source(what=src_what, url=j.get("url"),
                                       dated=j.get("posted"),
                                       quote=(j.get("title") or "")[:200])))
    return out


# one place, several spellings and granularities. Seen live: "Greater Bengaluru
# Area" and "Bengaluru Urban" for a company already known to be in Bengaluru.
PLACE_ALIASES = {"bangalore": "bengaluru", "bombay": "mumbai", "madras": "chennai",
                 "calcutta": "kolkata", "gurgaon": "gurugram", "poona": "pune",
                 "baroda": "vadodara", "cochin": "kochi", "trivandrum": "thiruvananthapuram"}
PLACE_FILLER = {"greater", "area", "urban", "rural", "district", "city", "region",
                "metropolitan", "metro", "division", "india", "the", "and", "new"}
HOME_ALIASES = {"ind": "india", "in": "india", "usa": "united states",
                "us": "united states", "united states of america": "united states",
                "uk": "united kingdom", "gb": "united kingdom"}


def _place_tokens(*texts) -> set[str]:
    out = set()
    for t in texts:
        for w in re.findall(r"[a-z]+", (t or "").lower()):
            w = PLACE_ALIASES.get(w, w)
            if len(w) > 2 and w not in PLACE_FILLER:
                out.add(w)
    return out


def _country(c) -> str:
    c = (c or "").strip().lower()
    return HOME_ALIASES.get(c, c)


def job_location_facts(jobs: list[dict], known_places: list[str],
                       declared_sites: Optional[int] = None,
                       home_country: Optional[str] = "India") -> list[Fact]:
    """Places the company is hiring that no address mentions.

    Conservative on purpose - every rule below was a wrong finding on live data:
      - remote listings are not premises;
      - a job abroad is not a premises on an Indian policy: it is context;
      - "Greater Bengaluru Area" is Bengaluru: places are compared by token,
        with aliases and filler words removed;
      - a new city only CONTRADICTS the form if it takes the count past what
        was declared. Declared 4 sites, seen 1 + 1 hiring city = consistent.
    """
    out: list[Fact] = []
    known = [_place_tokens(k) for k in known_places]
    home = _country(home_country)
    new_places, seen_tokens, abroad = [], [], {}
    for j in jobs:
        if j.get("remote"):
            continue
        country = _country(j.get("country"))
        if home and country and country != home:
            abroad.setdefault(j.get("country"), j)
            continue
        loc = (j.get("location") or "").strip()
        city = (j.get("city") or loc.split(",")[0]).strip()
        # the CITY only: the raw string carries the state, and two cities in
        # one state ("Roha", "Mumbai" - both Maharashtra) are not one place
        toks = _place_tokens(city)
        if not city or not toks:
            continue
        if any(toks & k for k in known) or any(toks & s for s in seen_tokens):
            continue
        seen_tokens.append(toks)
        new_places.append((city, loc, j))

    room = max(0, (declared_sites or 0) - len(known_places)) if declared_sites else 0
    for i, (city, loc, j) in enumerate(new_places):
        extra = i >= room
        out.append(Fact(f"jobsite_{city[:12].replace(' ','_')}",
                        "undeclared_site" if extra else "hiring_location",
                        city, "crustdata",
                        UNDECLARED if extra else CONSISTENT_UNCONFIRMED,
                        LOWER_BOUND, "company_id",
                        Source(what="POST /job/search -> job_listings[].location",
                               url=j.get("url"), dated=j.get("posted"),
                               quote=f"{j.get('title','')[:80]} - {loc or city}"),
                        note=("hiring here, and it takes the count past the "
                              f"{declared_sites or 0} sites declared" if extra else
                              "hiring here; within the number of sites declared")))
    if abroad:
        names = sorted(str(k) for k in abroad if k)
        first = next(iter(abroad.values()))
        out.append(Fact("hiring_abroad", "hiring_abroad", ", ".join(names), "crustdata",
                        CONSISTENT_UNCONFIRMED, LOWER_BOUND, "company_id",
                        Source(what="POST /job/search -> job_listings[].location.country",
                               url=first.get("url"), dated=first.get("posted"),
                               quote=f"open roles in {', '.join(names)}"),
                        note="group operations abroad; not premises on this policy"))
    return out


def growth_fact(history: list[dict]) -> Optional[Fact]:
    """Fast growth means controls lag. Use the slope, not just the level."""
    if not history or len(history) < 2:
        return None
    first, last = history[0], history[-1]
    a, b = first.get("total"), last.get("total")
    if not a or not b:
        return None
    pct = (b - a) / a * 100.0
    return Fact("growth", "headcount_growth_pct", round(pct, 1), "crustdata",
                MATCHES, DIRECT, "company_id",
                Source(what="POST /company/enrich -> headcount.history",
                       dated=last.get("date"),
                       quote=f"{a} on {first.get('date')} -> {b} on {last.get('date')}"))


# Words that make a result about an INCIDENT. Without one, a page that merely
# names the company (a directory, a vendor's client list, its own brochure) is
# not an adverse event. Kept specific on purpose: "notice" or "closure" alone
# match generic compliance articles - seen in the first live response.
INCIDENT = re.compile(
    r"\b(fire|blaze|gutted|explosion|blast|accident|killed|dead|death|died|"
    r"injured|injuries|collapse|collapsed|closure order|show cause|sealed|"
    r"fined|penalty|penalised|penalized)\b")


def _norm(text: str) -> str:
    """Same normalisation canonical_name() applies, so names compare like for like."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", (text or "").lower())).strip()


def adverse_facts(results: list[dict], company_name: str, city: str | None,
                  queries: list[str], complete: bool = True) -> list[Fact]:
    """Only counts if it clearly names THIS company AND describes an incident.
    A lookalike fire must never cause a decline, and a directory listing is not
    a fire. An empty result is a fact of its own, not a silence; a search that
    did not complete is cannot_verify, never "none found".

    `results` is adapt.web_results() output.
    """
    name = canonical_name(company_name) or ""
    place = _norm(city or "")
    hits = []
    for r in results:
        text = _norm(f"{r.get('title','')} {r.get('snippet','')}")
        named = bool(name) and f" {name} " in f" {text} "
        placed = (f" {place} " in f" {text} ") if place else True
        if named and placed and INCIDENT.search(text):
            hits.append(Fact(f"adverse_{len(hits)}", "adverse_event", True, "web",
                             MATCHES, DIRECT, "name_city",
                             Source(what="POST /web/search/live -> results[]",
                                    url=r.get("url"), dated=r.get("date"),
                                    quote=(r.get("title") or "")[:160],
                                    queries=queries)))
    if hits:
        return hits
    if not complete:
        # same shape as a timeout, so decide() HOLDS on it: we could not look
        return [Fact("ev_web", "evidence_unavailable", "/web/search/live", "derived",
                     CANNOT_VERIFY, note="web search did not complete (success=false "
                                         "or failed pages); we could not look")]
    return [Fact("adverse_none", "adverse_event", "none found", "web",
                 CONSISTENT_UNCONFIRMED, SEARCH_NEGATIVE, "name_city",
                 Source(what=f"POST /web/search/live returned {len(results)} results, "
                             f"none describing an incident at this company",
                        queries=queries),
                 note="we looked and found nothing; this is not the same as not looking")]


def _headcounts(cands: list[dict]) -> list[int]:
    out = []
    for c in cands:
        v = c.get("headcount.total")
        if v is None:
            v = (c.get("headcount") or {}).get("total")
        if isinstance(v, (int, float)) and v > 0:
            out.append(int(v))
    return sorted(out)


def cohort_facts(cands: list[dict], declared_headcount, total: int | None = None
                 ) -> list[Fact]:
    """Rung 2: we cannot check THIS company, so check the class it belongs to.

    This is real underwriting, and it works from nothing but two lines of text.
    """
    hc = _headcounts(cands)
    n = total or len(cands)
    if not hc:
        return [Fact("cohort", "class_benchmark", None, "derived", CANNOT_VERIFY,
                     note="no comparable companies with headcount in the record")]
    mid = hc[len(hc) // 2]
    src = Source(what=f"POST /company/search -> headcount.total across {n} comparable firms",
                 quote=f"sample of {len(hc)}: median {mid}, range {hc[0]}-{hc[-1]}")
    out = [Fact("cohort_median", "class_benchmark", mid, "crustdata",
                CONSISTENT_UNCONFIRMED, PROXY_RANGE, None, src,
                note=f"median headcount for this class is {mid}")]
    if declared_headcount:
        below = sum(1 for v in hc if v < declared_headcount)
        pct = round(below / len(hc) * 100)
        out.append(Fact("cohort_rank", "class_percentile", pct, "crustdata",
                        CONSISTENT_UNCONFIRMED, PROXY_RANGE, None, src,
                        note=(f"declared {declared_headcount} is larger than {pct}% of "
                              f"comparable firms; the declaration is not unusually "
                              f"low for this class")))
    return out
