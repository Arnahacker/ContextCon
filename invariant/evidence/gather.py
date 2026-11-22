"""gather(form) -> EvidenceResult. Resolve, then (only if resolved) enrich, jobs, news, sanctions.
A source that fails goes into `unavailable`; the others still run.

Credit budget is tight, so per case at most: identify (0.2/match), one enrich (2), one job search
(0.03/result, limit 25), and ONE web search (1) only when enrich returned no news, plus one
web enrich (1) for the article dates of web results that name the company."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from invariant.contracts import CallRecord, EvidenceResult, Resolution
from invariant.evidence import facts as F
from invariant.evidence.client import CrustdataClient, EvidenceUnavailable
from invariant.evidence.resolve import resolve
from invariant.shapes import Fact, Form

ENRICH_FIELDS = ["basic_info", "headcount", "locations", "taxonomy", "news"]
JOB_FIELDS = ["job_details.title", "job_details.url", "location.raw", "location.city", "metadata.date_added"]
NEWS_TERMS = "(fire OR explosion OR accident OR pollution OR strike OR closure OR court)"


# ---------------------------------------------------------------- request bodies (fixtures use these too)


def enrich_body(company_id: str) -> dict:
    return {"crustdata_company_ids": [int(company_id)], "fields": ENRICH_FIELDS}


def jobs_body(domain: str) -> dict:
    # Live finding: filtering by crustdata_company_id returns 0 results; primary_domain works.
    # No date filter in the request: keeps the request hash (cache + fixtures) stable across days.
    # The 12-month window is applied to metadata.date_added after the call.
    return {"filters": {"op": "and", "conditions": [
                {"field": "company.basic_info.primary_domain", "type": "=", "value": domain.lower()}]},
            "fields": JOB_FIELDS,
            "sorts": [{"field": "metadata.date_added", "order": "desc"}],
            "limit": 25}


def news_body(company_name: str, city: Optional[str]) -> dict:
    q = f"\"{F.core_name(company_name)}\""
    if city:
        q += f" {city}"
    return {"query": f"{q} {NEWS_TERMS}", "location": "IN", "sources": ["news", "web"]}


def web_enrich_body(urls: list[str]) -> dict:
    return {"urls": urls[:10]}


def sanctions_body(company_name: str) -> dict:
    return {"queries": {"q": {"schema": "Company",
                              "properties": {"name": [company_name], "jurisdiction": ["in"]}}}}


# ---------------------------------------------------------------- gather


def _call(client: CrustdataClient, endpoint: str, body, calls: list[CallRecord]):
    try:
        data, rec = client.post(endpoint, body)
    except EvidenceUnavailable as e:
        if e.record:
            calls.append(e.record)
        raise
    calls.append(rec)
    return data


def _first_company_data(data) -> dict:
    for item in data if isinstance(data, list) else []:
        for m in (item or {}).get("matches") or []:
            if m.get("company_data"):
                return m["company_data"]
    return {}


def gather(form: Form, client: Optional[CrustdataClient] = None, now: Optional[datetime] = None) -> EvidenceResult:
    client = client or CrustdataClient()
    now = now or datetime.now(timezone.utc)  # the only clock read in the evidence layer
    fetched = now.isoformat(timespec="seconds")

    res, calls = resolve(form, client)
    if res.status != "resolved":
        return EvidenceResult(resolution=res, calls=calls,
                              unavailable=["identify"] if res.status == "unavailable" else [])

    facts: list[Fact] = [F.company_fact(res, fetched)]
    unavailable: list[str] = []
    name = res.name or form.company_name or ""

    # enrich
    company_data: dict = {}
    try:
        company_data = _first_company_data(_call(client, "/company/enrich", enrich_body(res.company_id), calls))
        facts += F.enrich_facts(form, company_data, fetched)
    except EvidenceUnavailable:
        unavailable.append("enrich")
    cities = F.office_cities(company_data)

    # jobs (last 12 months), by domain; a company with no domain has no job search (no fact)
    if res.domain:
        try:
            data = _call(client, "/job/search", jobs_body(res.domain), calls) or {}
            since = (now - timedelta(days=365)).date().isoformat()
            facts += F.job_facts(form, data.get("job_listings") or [], cities, fetched, since=since)
        except EvidenceUnavailable:
            unavailable.append("job_search")

    # news, primary: enrich news[] (dated, linked to the company id)
    news = company_data.get("news") or []
    facts += F.news_facts(news, name, fetched)
    # news, secondary: ONE web search, only when enrich had no news
    if not news:
        facts += _web_news(client, form, res, name, cities, fetched, calls, unavailable)

    # sanctions: only with a key, silently skipped otherwise
    if os.environ.get("OPENSANCTIONS_API_KEY"):
        try:
            data = _call(client, "opensanctions:/match/default", sanctions_body(name), calls) or {}
            facts += F.sanctions_facts(data, fetched)
        except EvidenceUnavailable:
            unavailable.append("sanctions")

    return EvidenceResult(resolution=res, facts=facts, unavailable=unavailable, calls=calls)


def _web_news(client, form, res, name, cities, fetched, calls, unavailable) -> list[Fact]:
    city = form.city or (cities[0] if cities else None)
    match_cities = list(dict.fromkeys([c for c in [form.city, *cities] if c]))
    try:
        data = _call(client, "/web/search/live", news_body(name, city), calls) or {}
    except EvidenceUnavailable:
        unavailable.append("web_search")
        return []
    results = data.get("results") or []
    urls = F.adverse_candidates(results, name, match_cities, res.domain)
    dates: dict = {}
    if urls:
        try:
            pages = _call(client, "/web/enrich/live", web_enrich_body(urls), calls) or []
            for p in pages if isinstance(pages, list) else []:
                if p.get("success"):
                    dates[p.get("url")] = F.publish_date(p.get("content"))
        except EvidenceUnavailable:
            pass  # only the date is lost: facts keep dated=None ("date unknown")
    return F.adverse_facts(results, name, match_cities, res.domain, dates, fetched)
