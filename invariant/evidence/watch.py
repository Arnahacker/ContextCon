"""Company watcher for the demo companies.

A watch takes the company's record as a baseline, then each check reports what
changed on record since. Offline, the changes come from a fixed script in
fixtures/crustdata/watch/events.json, so the demo repeats exactly. Live, the same
companies can be watched but no change is ever reported: live re-checks against
Crustdata are not built yet, and a change is never invented. Every change becomes
a Fact with its Crustdata source.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from invariant.shapes import Fact, Source

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "fixtures" / "crustdata"
EVENTS_FILE = FIXTURES / "watch" / "events.json"


class WatchUnavailable(Exception):
    """Watching is not possible for this company in this mode."""


def offline() -> bool:
    on = lambda k: os.environ.get(k, "").lower() in ("1", "true", "yes")  # noqa: E731
    return on("INVARIANT_OFFLINE") or on("INVARIANT_EVIDENCE_OFFLINE")


def _script() -> dict[str, Any]:
    return json.loads(EVENTS_FILE.read_text(encoding="utf-8"))["companies"]


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _require(company_id: str) -> dict[str, Any]:
    entry = _script().get(str(company_id))
    if entry is None:
        raise WatchUnavailable(f"Company {company_id} is not one of the demo companies.")
    return entry


def baseline(company_id: str) -> dict[str, Any]:
    """The company's record when the watch starts, read from the enrich fixture."""
    entry = _require(company_id)
    raw = json.loads((FIXTURES / "company_enrich" / entry["fixture"]).read_text(encoding="utf-8"))
    d = raw[0]["matches"][0]["company_data"]
    b, h, loc = d.get("basic_info") or {}, d.get("headcount") or {}, d.get("locations") or {}
    return {
        "company_id": str(company_id),
        "name": b.get("name"),
        "domain": b.get("primary_domain") or b.get("website"),
        "city": str(loc.get("headquarters") or "").split(",")[0] or None,
        "headquarters": loc.get("headquarters"),
        "headcount": h.get("total"),
        "industry": (d.get("taxonomy") or {}).get("professional_network_industry"),
        "source": {"what": "POST /company/enrich", "quote": f"crustdata_company_id: {company_id}"},
    }


def watchable() -> list[dict[str, Any]]:
    """The demo companies that can be watched."""
    return [baseline(cid) for cid in sorted(_script())]


def _fact(company_id: str, n: int, i: int, ch: dict[str, Any], fetched: str) -> Fact:
    return Fact(
        id=f"watch_{company_id}_{n}_{i}",
        field=ch["field"],
        value=ch["after"],
        origin="web" if ch["endpoint"].startswith("POST /web") else "crustdata",
        evidence_kind="direct",
        status="undeclared" if ch["field"] in ("hazardous_activity", "adverse_event", "sites") else "consistent_unconfirmed",
        company_match="company_id",
        source=Source(what=f"{ch['endpoint']} -> {ch['path']}", url=ch.get("url"), dated=ch.get("dated"),
                      fetched=fetched, quote=ch["quote"]),
    )


def check(company_id: str, n: int) -> dict[str, Any]:
    """Check number n (0-based) since the watch started: what changed on record."""
    entry = _require(company_id)
    fetched = _now()
    script = entry["checks"] if offline() else []  # live: no scripted changes, and no change is invented
    changes = script[n] if n < len(script) else []
    out = []
    for i, ch in enumerate(changes):
        f = _fact(company_id, n, i, ch, fetched)  # refuses to exist without a source
        out.append({"field": ch["field"], "before": ch["before"], "after": ch["after"], "text": ch["text"],
                    "fact": f.model_dump(mode="json")})
    return {"company_id": str(company_id), "checked": fetched, "changes": out,
            "mode": "offline" if offline() else "live"}
