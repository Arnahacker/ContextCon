"""The one Crustdata client. Every external call in the evidence layer goes through `post`.

Order of operations for a call:
  1. fault injection (INVARIANT_FAULT=web_search:timeout or `faults=`)  -> EvidenceUnavailable
  2. sqlite request-hash cache (data/cache.sqlite)                        -> cached=True
  3. offline: fixtures/crustdata/   |   live: rate limit + HTTP with retry/backoff
  4. store in cache, record a CallRecord in the instance log and the global METER
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Optional

import httpx

from invariant.contracts import CallRecord

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CACHE = Path(os.environ.get("INVARIANT_DATA", ROOT / "data")) / "cache.sqlite"
FIXTURES = ROOT / "fixtures" / "crustdata"

CRUSTDATA_BASE = "https://api.crustdata.com"
OPENSANCTIONS_BASE = "https://api.opensanctions.org"
OPENSANCTIONS_PREFIX = "opensanctions:"  # endpoint "opensanctions:/match/default"
API_VERSION = "2025-11-01"
TIMEOUT_S = 20.0
MAX_RETRIES = 3

# endpoint -> (source name used in `unavailable` / INVARIANT_FAULT, requests per minute)
ENDPOINTS: dict[str, tuple[str, int]] = {
    "/company/identify": ("identify", 30),
    "/company/enrich": ("enrich", 15),
    "/job/search": ("job_search", 30),
    "/web/search/live": ("web_search", 10),
    "/web/enrich/live": ("web_enrich", 10),
    "opensanctions:/match/default": ("sanctions", 60),
}


class EvidenceUnavailable(Exception):
    """A source failed for good (timeout, 5xx after retries, missing fixture, injected fault)."""

    def __init__(self, endpoint: str, reason: str, record: Optional[CallRecord] = None):
        super().__init__(f"{endpoint}: {reason}")
        self.endpoint = endpoint
        self.reason = reason
        self.record = record

    @property
    def source(self) -> str:
        return source_name(self.endpoint)


def source_name(endpoint: str) -> str:
    return ENDPOINTS.get(endpoint, (endpoint.strip("/").replace("/", "_"), 0))[0]


def canonical(body: Any) -> str:
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def request_hash(endpoint: str, body: Any) -> str:
    return hashlib.sha256((endpoint + "\n" + canonical(body)).encode("utf-8")).hexdigest()


def endpoint_slug(endpoint: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", endpoint.lower()).strip("_")


def _loose(x: Any) -> Any:
    """Fixture-index matching ignores case and extra whitespace in strings."""
    if isinstance(x, str):
        return " ".join(x.lower().split())
    if isinstance(x, list):
        return [_loose(v) for v in x]
    if isinstance(x, dict):
        return {k: _loose(v) for k, v in x.items()}
    return x


# ---------------------------------------------------------------- meter


class Meter:
    """Running totals the API layer can show: credits spent, cache hits, failures."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        self.calls = 0
        self.cached = 0
        self.failed = 0
        self.credits = 0.0
        self.by_endpoint: dict[str, dict[str, float]] = {}
        self.recent: deque = deque(maxlen=50)

    def add(self, r: CallRecord) -> None:
        with self._lock:
            self.calls += 1
            self.cached += int(r.cached)
            self.failed += int(not r.ok)
            self.credits += r.credits
            e = self.by_endpoint.setdefault(r.endpoint, {"calls": 0, "cached": 0, "credits": 0.0})
            e["calls"] += 1
            e["cached"] += int(r.cached)
            e["credits"] += r.credits
            self.recent.append(r.model_dump(mode="json"))

    def snapshot(self) -> dict:
        with self._lock:
            return {"calls": self.calls, "cached": self.cached, "failed": self.failed,
                    "credits": round(self.credits, 4),
                    "by_endpoint": {k: dict(v) for k, v in self.by_endpoint.items()},
                    "recent": list(self.recent)}


METER = Meter()


def meter_snapshot() -> dict:
    """Totals for every call made in this process (live, fixture, cached or failed)."""
    return METER.snapshot()


# ---------------------------------------------------------------- client


def _parse_faults(spec: Optional[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in (spec or "").split(","):
        if ":" in part:
            k, v = part.split(":", 1)
            out[k.strip()] = v.strip()
        elif part.strip():
            out[part.strip()] = "error"
    return out


class CrustdataClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        offline: Optional[bool] = None,
        cache_path: Optional[Path | str] = None,
        fixtures_dir: Optional[Path | str] = None,
        faults: Optional[dict[str, str]] = None,
        transport: Optional[httpx.BaseTransport] = None,
        meter: Meter = METER,
    ):
        self.api_key = api_key if api_key is not None else os.environ.get("CRUSTDATA_API_KEY", "")
        self.sanctions_key = os.environ.get("OPENSANCTIONS_API_KEY", "")
        if offline is None:
            offline = (os.environ.get("INVARIANT_OFFLINE", "").lower() in ("1", "true", "yes")
                       or os.environ.get("INVARIANT_EVIDENCE_OFFLINE", "").lower() in ("1", "true", "yes")
                       or not self.api_key)
        self.offline = offline
        self.mode = "offline" if offline else "live"
        self.fixtures_dir = Path(fixtures_dir or FIXTURES)
        self._faults = faults or {}
        self.meter = meter
        self.log: list[CallRecord] = []
        self.sleep = time.sleep  # patchable in tests
        self._http = httpx.Client(timeout=TIMEOUT_S, transport=transport)
        self._windows: dict[str, deque] = {}
        self._lock = threading.Lock()
        path = Path(cache_path or DEFAULT_CACHE)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, endpoint TEXT, body TEXT,"
            " response TEXT, credits REAL, created REAL)"
        )
        self._db.commit()

    # ------------------------------------------------------------ public

    def post(self, endpoint: str, body: Any) -> tuple[Any, CallRecord]:
        h = request_hash(endpoint, body)
        t0 = time.monotonic()
        src = source_name(endpoint)

        faults = {**_parse_faults(os.environ.get("INVARIANT_FAULT")), **self._faults}  # read at call time
        if src in faults:
            self._fail(endpoint, h, t0, f"injected fault: {faults[src]}")

        hit = self._cache_get(h)
        if hit is not None:
            return hit, self._record(endpoint, h, True, 0.0, True, t0)

        if self.offline:
            data = self._fixture(endpoint, body, h)
            if data is None:
                self._fail(endpoint, h, t0, f"no fixture (slug {endpoint_slug(endpoint)}, hash {h}, body {canonical(body)})")
            credits = 0.0
        else:
            data, credits = self._live(endpoint, body, h, t0)

        self._cache_put(h, endpoint, body, data, credits)
        return data, self._record(endpoint, h, False, credits, True, t0)

    # ------------------------------------------------------------ internals

    def _record(self, endpoint, h, cached, credits, ok, t0, error=None) -> CallRecord:
        r = CallRecord(endpoint=endpoint, request_hash=h, cached=cached, credits=credits, ok=ok,
                       ms=int((time.monotonic() - t0) * 1000), error=error)
        self.log.append(r)
        self.meter.add(r)
        return r

    def _fail(self, endpoint, h, t0, reason, credits=0.0):
        r = self._record(endpoint, h, False, credits, False, t0, error=reason)
        raise EvidenceUnavailable(endpoint, reason, r)

    def _key(self, h: str) -> str:
        return f"{self.mode}:{h}"  # fixtures never leak into the live cache

    def _cache_get(self, h: str) -> Any:
        with self._lock:
            row = self._db.execute("SELECT response FROM cache WHERE key=?", (self._key(h),)).fetchone()
        return json.loads(row[0]) if row else None

    def _cache_put(self, h, endpoint, body, data, credits) -> None:
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO cache VALUES (?,?,?,?,?,?)",
                (self._key(h), endpoint, canonical(body), json.dumps(data, ensure_ascii=False), credits, time.time()),
            )
            self._db.commit()

    def _fixture(self, endpoint: str, body: Any, h: str) -> Any:
        by_hash = self.fixtures_dir / endpoint_slug(endpoint) / f"{h}.json"
        if by_hash.exists():
            return json.loads(by_hash.read_text(encoding="utf-8"))
        index = self.fixtures_dir / "index.json"
        if index.exists():
            want = _loose(body)
            for e in json.loads(index.read_text(encoding="utf-8")).get("entries", []):
                if e["endpoint"] == endpoint and _loose(e["body"]) == want:
                    return json.loads((self.fixtures_dir / e["response"]).read_text(encoding="utf-8"))
        return None

    def _throttle(self, endpoint: str) -> None:
        rpm = ENDPOINTS.get(endpoint, ("", 10))[1]
        with self._lock:
            w = self._windows.setdefault(endpoint, deque())
            now = time.monotonic()
            while w and now - w[0] >= 60:
                w.popleft()
            wait = 60 - (now - w[0]) if len(w) >= rpm else 0.0
        if wait > 0:
            self.sleep(wait)
        with self._lock:
            self._windows[endpoint].append(time.monotonic())

    def _live(self, endpoint: str, body: Any, h: str, t0: float) -> tuple[Any, float]:
        if endpoint.startswith(OPENSANCTIONS_PREFIX):
            url = OPENSANCTIONS_BASE + endpoint[len(OPENSANCTIONS_PREFIX):]
            headers = {"Authorization": f"ApiKey {self.sanctions_key}", "content-type": "application/json"}
        else:
            url = CRUSTDATA_BASE + endpoint
            headers = {"authorization": f"Bearer {self.api_key}", "x-api-version": API_VERSION,
                       "content-type": "application/json"}
        credits = 0.0
        reason = "unknown"
        for attempt in range(MAX_RETRIES + 1):
            if attempt:
                self.sleep(min(2 ** (attempt - 1), 8))
            self._throttle(endpoint)
            try:
                resp = self._http.post(url, headers=headers, content=canonical(body))
            except httpx.TimeoutException:
                reason = "timeout"
                continue
            except httpx.TransportError as e:
                reason = f"transport error: {type(e).__name__}"
                continue
            try:
                credits += float(resp.headers.get("x-credits-used", "0") or 0)
            except ValueError:
                pass
            if resp.status_code == 404 and endpoint == "/company/identify":
                return [], credits  # docs: no match may also come back as 404
            if resp.status_code == 429 or resp.status_code >= 500:
                reason = f"HTTP {resp.status_code}"
                continue
            if resp.status_code >= 400:
                self._fail(endpoint, h, t0, f"HTTP {resp.status_code}: {resp.text[:200]}", credits)
            try:
                return resp.json(), credits
            except ValueError:
                self._fail(endpoint, h, t0, "response is not JSON", credits)
        self._fail(endpoint, h, t0, f"{reason} after {MAX_RETRIES} retries", credits)
