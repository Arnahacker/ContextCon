"""Append-only case log in sqlite. Every step is written as it happens, so a
killed process resumes from the log (and the evidence/LLM caches mean nothing
is fetched or charged twice)."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

DB_PATH = Path(os.environ.get("INVARIANT_DATA", Path(__file__).resolve().parents[2] / "data")) / "cases.sqlite"
_lock = threading.Lock()


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.execute(
        "CREATE TABLE IF NOT EXISTS events (case_id TEXT, seq INTEGER, kind TEXT, payload TEXT, at TEXT,"
        " PRIMARY KEY (case_id, seq))"
    )
    c.execute("CREATE TABLE IF NOT EXISTS cases (case_id TEXT PRIMARY KEY, created TEXT, prompt TEXT)")
    return c


def new_case(prompt: str) -> str:
    case_id = uuid.uuid4().hex[:12]
    with _lock, _conn() as c:
        c.execute("INSERT INTO cases VALUES (?,?,?)", (case_id, now_iso(), prompt))
    append(case_id, "prompt", {"text": prompt})
    return case_id


def append(case_id: str, kind: str, payload: Any) -> None:
    with _lock, _conn() as c:
        (seq,) = c.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM events WHERE case_id=?", (case_id,)).fetchone()
        c.execute(
            "INSERT INTO events VALUES (?,?,?,?,?)",
            (case_id, seq, kind, json.dumps(payload, ensure_ascii=False, default=str), now_iso()),
        )


def events(case_id: str) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT seq, kind, payload, at FROM events WHERE case_id=? ORDER BY seq", (case_id,)
        ).fetchall()
    return [{"seq": s, "kind": k, "payload": json.loads(p), "at": a} for s, k, p, a in rows]


def last(case_id: str, kind: str) -> Optional[dict]:
    for e in reversed(events(case_id)):
        if e["kind"] == kind:
            return e["payload"]
    return None


def list_cases(limit: int = 50) -> list[dict]:
    with _conn() as c:
        rows = c.execute("SELECT case_id, created, prompt FROM cases ORDER BY created DESC LIMIT ?", (limit,)).fetchall()
    return [{"case_id": i, "created": t, "prompt": p} for i, t, p in rows]
