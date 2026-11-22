"""Crustdata client: cached, metered, and safe to call a hundred times.

Caching is here from the first commit, not bolted on later. You will run the
same ten test cases all afternoon and the budget is finite.
"""
from __future__ import annotations
import os, time, json, pathlib
from typing import Any, Optional

import httpx

from ..runlog import request_hash, cache_get, cache_put
from ..ledger import Ledger

BASE = os.environ.get("CRUSTDATA_BASE", "https://api.crustdata.com")
VERSION = "2025-11-01"
MOCKS = pathlib.Path(os.environ.get("CRUSTDATA_MOCKS", "./mocks"))


class EvidenceUnavailable(Exception):
    """A source did not answer. NOT the same as 'it answered and found nothing'."""
    def __init__(self, what: str, why: str = ""):
        super().__init__(f"{what}: {why}")
        self.what, self.why = what, why


class Crustdata:
    def __init__(self, ledger: Ledger, api_key: Optional[str] = None,
                 mode: Optional[str] = None, timeout: float = 20.0):
        self.ledger = ledger
        self.key = api_key or os.environ.get("CRUSTDATA_API_KEY", "")
        # live | mock . mock reads ./mocks/<endpoint>.json so four people can
        # build in parallel without a key and without spending credits.
        self.mode = mode or os.environ.get("CRUSTDATA_MODE", "live" if self.key else "mock")
        self.timeout = timeout

    # ------------------------------------------------------------------ core
    def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        key = request_hash(path, payload)
        hit = cache_get(key)
        if hit is not None:
            self.ledger.add(path, credits=0, cached=True)
            return hit

        if self.mode == "mock":
            data = self._mock(path)
            cache_put(key, data)
            self.ledger.add(path, credits=0, cached=True, note="mock")
            return data

        t0 = time.monotonic()
        try:
            r = httpx.post(f"{BASE}{path}", json=payload, timeout=self.timeout,
                           headers={"authorization": f"Bearer {self.key}",
                                    "x-api-version": VERSION,
                                    "content-type": "application/json"})
        except (httpx.TimeoutException, httpx.TransportError) as e:
            self.ledger.add(path, ok=False, note=f"unreachable: {type(e).__name__}")
            raise EvidenceUnavailable(path, type(e).__name__)
        ms = int((time.monotonic() - t0) * 1000)

        if r.status_code == 429:
            self.ledger.add(path, ok=False, ms=ms, note="rate limited")
            raise EvidenceUnavailable(path, "rate limited")
        if r.status_code >= 500:
            self.ledger.add(path, ok=False, ms=ms, note=f"HTTP {r.status_code}")
            raise EvidenceUnavailable(path, f"HTTP {r.status_code}")
        if r.status_code >= 400:
            self.ledger.add(path, ok=False, ms=ms, note=f"HTTP {r.status_code}")
            raise ValueError(f"{path} rejected the request: {r.status_code} {r.text[:200]}")

        data = r.json()
        self.ledger.add(path, credits=_credits_from(data, r.headers), ms=ms)
        cache_put(key, data)
        return data

    def _mock(self, path: str) -> dict[str, Any]:
        p = MOCKS / (path.strip("/").replace("/", "_") + ".json")
        if not p.exists():
            raise EvidenceUnavailable(path, f"no mock at {p}")
        return json.loads(p.read_text(encoding="utf-8"))

    # -------------------------------------------------------------- endpoints
    # Identifiers are PLURAL ARRAYS of exactly one type per call.
    # Verified against the live API on 2026-11-22.

    def identify(self, names=None, domains=None, exact_match=None):
        body: dict[str, Any] = {}
        if names:   body["names"] = names if isinstance(names, list) else [names]
        if domains: body["domains"] = domains if isinstance(domains, list) else [domains]
        if exact_match is not None: body["exact_match"] = exact_match
        return self.post("/company/identify", body)

    ENRICH_FIELDS = ["basic_info", "headcount", "locations", "taxonomy", "hiring"]

    def enrich(self, crustdata_company_ids=None, domains=None, names=None, fields=None):
        body: dict[str, Any] = {"fields": fields or self.ENRICH_FIELDS}
        if crustdata_company_ids:
            body["crustdata_company_ids"] = (crustdata_company_ids
                if isinstance(crustdata_company_ids, list) else [crustdata_company_ids])
        if domains: body["domains"] = domains if isinstance(domains, list) else [domains]
        if names:   body["names"] = names if isinstance(names, list) else [names]
        return self.post("/company/enrich", body)

    def company_search(self, filters: dict, limit=25, fields=None, sorts=None):
        body: dict[str, Any] = {"filters": filters, "limit": limit}
        if fields: body["fields"] = fields
        if sorts:  body["sorts"] = sorts
        return self.post("/company/search", body)

    def job_search(self, filters: dict, limit=50):
        """Verified live 2026-11-22. Response: {job_listings, next_cursor, total_count}.
        Filter on company.basic_info.crustdata_company_id - "company_id" is a 400."""
        return self.post("/job/search", {"filters": filters, "limit": limit})

    def jobs_for_company(self, crustdata_company_id: int, limit=50):
        return self.job_search({"field": "company.basic_info.crustdata_company_id",
                                "type": "=", "value": crustdata_company_id}, limit)

    def people_search(self, filters: dict, limit=25, fields=None):
        body: dict[str, Any] = {"filters": filters, "limit": limit}
        if fields: body["fields"] = fields
        return self.post("/person/search", body)

    def web_search(self, query: str, sources=("web",)):
        """Verified live 2026-11-22. There is no `limit` param (it was ignored).
        Response: {success, query, timestamp, results[], metadata}. The result
        shape varies by source, so pin the source we have parsed."""
        return self.post("/web/search/live", {"query": query, "sources": list(sources)})


def _credits_from(data: dict, headers) -> float:
    """Crustdata reports what each call cost. Read it rather than guessing."""
    for k in ("credits_spent", "credits", "_credits"):
        v = data.get(k) if isinstance(data, dict) else None
        if isinstance(v, (int, float)):
            return float(v)
    for h in ("x-credits-used", "x-credits-spent", "x-credit-cost"):  # -used seen live
        if h in headers:
            try:
                return float(headers[h])
            except ValueError:
                pass
    return 0.0
