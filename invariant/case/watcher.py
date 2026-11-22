"""Watched companies, kept in the case database. A watch stores the company's
baseline and every check's result, so the page can show what changed and when."""
from __future__ import annotations

import json
from typing import Any

from invariant.evidence import watch

from .store import _conn, _lock, now_iso


def _db():
    c = _conn()
    c.execute("CREATE TABLE IF NOT EXISTS watches (company_id TEXT PRIMARY KEY, started TEXT,"
              " baseline TEXT, checks TEXT)")
    return c


def _row(r) -> dict[str, Any]:
    cid, started, base, checks = r
    return {"company_id": cid, "started": started, "baseline": json.loads(base), "checks": json.loads(checks)}


def _get(company_id: str) -> dict[str, Any] | None:
    with _db() as c:
        r = c.execute("SELECT company_id, started, baseline, checks FROM watches WHERE company_id=?",
                      (str(company_id),)).fetchone()
    return _row(r) if r else None


def overview() -> dict[str, Any]:
    """Every demo company, with its watch (if any)."""
    with _db() as c:
        rows = {r[0]: _row(r) for r in c.execute("SELECT company_id, started, baseline, checks FROM watches")}
    companies = [{**b, "watch": rows.get(b["company_id"])} for b in watch.watchable()]
    return {"available": True, "mode": "offline" if watch.offline() else "live", "companies": companies}


def start(company_id: str) -> dict[str, Any]:
    """Start watching. Watching a company twice keeps the first watch."""
    existing = _get(company_id)
    if existing:
        return existing
    base = watch.baseline(company_id)
    with _lock, _db() as c:
        c.execute("INSERT OR IGNORE INTO watches VALUES (?,?,?,?)",
                  (str(company_id), now_iso(), json.dumps(base, ensure_ascii=False), "[]"))
    return _get(company_id)


def stop(company_id: str) -> None:
    with _lock, _db() as c:
        c.execute("DELETE FROM watches WHERE company_id=?", (str(company_id),))


def check_now(company_id: str) -> dict[str, Any]:
    w = _get(company_id)
    if w is None:
        raise KeyError(company_id)
    result = watch.check(company_id, len(w["checks"]))
    w["checks"].append(result)
    with _lock, _db() as c:
        c.execute("UPDATE watches SET checks=? WHERE company_id=?",
                  (json.dumps(w["checks"], ensure_ascii=False), str(company_id)))
    return w
