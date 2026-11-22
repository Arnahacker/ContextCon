"""Company resolution via POST /company/identify. Never a guess: if more than one plausible
company survives the filters, the status is "ambiguous" and the candidates are listed.

Identify-by-name returns up to 25 matches, often several tied (e.g. 0.80). So among matches
within AMBIGUITY_GAP of the best plausible score we:
  1. drop shell records (no primary_domain AND no employee_count_range) and "myself only" pages,
  2. drop clearly non-Indian records (this desk insures Indian risks unless form.countries says otherwise),
  3. keep one record per primary_domain (the largest),
  4. prefer candidates whose industries fit form.industry (if any fit),
  5. prefer an exact core-name match ("Super Tannery Ltd" == "Super Tannery Limited"),
  6. prefer candidates with a domain.
One survivor -> resolved. Two or more -> ambiguous (at most MAX_CANDIDATES).
"""
from __future__ import annotations

import re
from typing import Optional

from invariant.contracts import CallRecord, Candidate, Resolution
from invariant.evidence.client import CrustdataClient, EvidenceUnavailable
from invariant.evidence.facts import norm, norm_company, occupancy_hints
from invariant.shapes import Form

AMBIGUITY_GAP = 0.05
MAX_CANDIDATES = 3
FOREIGN_MARKERS = ["(u.k.)", "(uk)", " uk limited", "u.k. limited", "united kingdom", "united states", " inc.",
                   " llc", " gmbh", " pty", "s.a.", "new york", "london", "dubai", "singapore"]
FOREIGN_TLDS = (".uk", ".us", ".au", ".de", ".pt", ".br", ".za", ".es", ".fr", ".it", ".ae", ".sg", ".my",
                ".bd", ".pk", ".vn", ".ao", ".mx", ".ca", ".nl")
MANUFACTURING_WORDS = ("manufactur", "textile", "leather", "apparel", "footwear", "garment", "tannery")
RANGE_ORDER = ["myself only", "1-10", "2-10", "11-50", "51-200", "201-500", "501-1000", "1001-5000",
               "5001-10000", "10001+"]


def identify_body(form: Form) -> list[dict]:
    """Bodies to try, in order: domain first (exact, if given), then name."""
    bodies = []
    if form.domain:
        bodies.append({"domains": [form.domain.strip().lower()]})
    if form.company_name:
        bodies.append({"names": [form.company_name.strip()]})
    return bodies


def _matches(data) -> list[dict]:
    out = []
    for item in data if isinstance(data, list) else []:
        out.extend((item or {}).get("matches") or [])
    return out


def _bi(m: dict) -> dict:
    return (m.get("company_data") or {}).get("basic_info") or {}


def _cid(m: dict) -> str:
    return str((m.get("company_data") or {}).get("crustdata_company_id"))


def _conf(m: dict) -> float:
    return float(m.get("confidence_score") or 0)


def _location(m: dict) -> Optional[str]:
    cd = m.get("company_data") or {}
    hq = (cd.get("locations") or {}).get("headquarters")
    if hq:
        return hq
    d = _bi(m).get("description") or ""
    x = re.search(r"based (?:out of|in) ([^.]+)", d)
    if not x:
        return None
    loc = re.sub(r",?\s*India\s*$", "", x.group(1).strip())
    return loc or None


def _candidate(m: dict) -> Candidate:
    bi = _bi(m)
    return Candidate(company_id=_cid(m), name=bi.get("name") or "", domain=bi.get("primary_domain"),
                     location=_location(m), confidence=_conf(m))


def _is_shell(m: dict) -> bool:
    bi = _bi(m)
    rng = (bi.get("employee_count_range") or "").lower()
    return (not bi.get("primary_domain") and not rng) or rng == "myself only"


def _is_foreign(m: dict) -> bool:
    bi = _bi(m)
    text = f" {(bi.get('name') or '').lower()} {(bi.get('description') or '').lower()} "
    domain = (bi.get("primary_domain") or "").lower()
    return any(k in text for k in FOREIGN_MARKERS) or domain.endswith(FOREIGN_TLDS)


def _fits(m: dict, industry: str) -> bool:
    bi = _bi(m)
    texts = list(bi.get("industries") or []) + [bi.get("description") or "", bi.get("name") or ""]
    if industry in occupancy_hints(texts, bi.get("name")):
        return True
    return industry != "other" and any(w in " ".join(bi.get("industries") or []).lower() for w in MANUFACTURING_WORDS)


def _size(m: dict) -> int:
    rng = (_bi(m).get("employee_count_range") or "").lower()
    return RANGE_ORDER.index(rng) if rng in RANGE_ORDER else -1


def _prefer(ms: list[dict], keep) -> list[dict]:
    kept = [m for m in ms if keep(m)]
    return kept or ms


def plausible(matches: list[dict], form: Form) -> list[dict]:
    """The filter pipeline described in the module docstring. Returns survivors, best first."""
    best: dict[str, dict] = {}
    for m in matches:
        if m.get("company_data") and (_cid(m) not in best or _conf(m) > _conf(best[_cid(m)])):
            best[_cid(m)] = m
    ms = [m for m in best.values() if not _is_shell(m)]
    indian = not form.countries or any(norm(c) in ("in", "ind", "india") for c in form.countries)
    if indian:
        ms = [m for m in ms if not _is_foreign(m)]
    if not ms:
        return []
    ms.sort(key=lambda m: -_conf(m))
    top = _conf(ms[0])
    ms = [m for m in ms if top - _conf(m) <= AMBIGUITY_GAP]
    by_domain: dict[str, dict] = {}
    rest = []
    for m in ms:
        d = (_bi(m).get("primary_domain") or "").lower()
        if not d:
            rest.append(m)
        elif d not in by_domain or _size(m) > _size(by_domain[d]):
            by_domain[d] = m
    ms = sorted(list(by_domain.values()) + rest, key=lambda m: -_conf(m))
    if form.industry:
        ms = _prefer(ms, lambda m: _fits(m, form.industry))
    core = norm_company(form.company_name)
    if core:
        ms = _prefer(ms, lambda m: norm_company(_bi(m).get("name")) == core)
    return _prefer(ms, lambda m: bool(_bi(m).get("primary_domain")))


def resolve(form: Form, client: Optional[CrustdataClient] = None) -> tuple[Resolution, list[CallRecord]]:
    client = client or CrustdataClient()
    calls: list[CallRecord] = []
    survivors: list[dict] = []
    tried = False
    for body in identify_body(form):
        tried = True
        try:
            data, rec = client.post("/company/identify", body)
        except EvidenceUnavailable as e:
            if e.record:
                calls.append(e.record)
            return Resolution(status="unavailable"), calls
        calls.append(rec)
        ms = _matches(data)
        if "domains" in body:  # exact: trust the domain match, no name heuristics
            ms = [m for m in ms if (_bi(m).get("primary_domain") or "").lower() == body["domains"][0]] or ms
            survivors = sorted(ms, key=lambda m: -_conf(m))[:1]
        else:
            survivors = plausible(ms, form)
        if survivors:
            break
    if not tried or not survivors:
        return Resolution(status="not_found"), calls
    if len(survivors) > 1:
        return Resolution(status="ambiguous", candidates=[_candidate(m) for m in survivors[:MAX_CANDIDATES]]), calls
    top = _candidate(survivors[0])
    return Resolution(status="resolved", company_id=top.company_id, name=top.name, domain=top.domain,
                      candidates=[top]), calls
