"""Append-only event log + response cache + exactly-once.

Kill the process at any point and start it again: the run replays from the
log, re-uses cached responses, and never repeats a call that sends anything.
"""
from __future__ import annotations
import hashlib, json, os, pathlib, threading, time
from typing import Any, Callable, Optional

ROOT = pathlib.Path(os.environ.get("INVARIANT_DATA", "./data"))
RUNS, CACHE = ROOT / "runs", ROOT / "cache"
_lock = threading.Lock()


def _ensure():
    RUNS.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(parents=True, exist_ok=True)


def request_hash(name: str, payload: Any) -> str:
    blob = json.dumps({"n": name, "p": payload}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:24]


class RunLog:
    def __init__(self, run_id: str):
        _ensure()
        self.run_id = run_id
        self.path = RUNS / f"{run_id}.jsonl"
        self._done: dict[str, Any] = {}
        self._replay()

    def _replay(self):
        if not self.path.exists():
            return
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("kind") == "once" and "key" in ev:
                self._done[ev["key"]] = ev.get("result")

    def append(self, kind: str, **data):
        _ensure()
        ev = {"t": time.time(), "kind": kind, **data}
        with _lock:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(ev, default=str) + "\n")
        return ev

    def events(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(l) for l in self.path.read_text(encoding="utf-8").splitlines() if l.strip()]

    # ---- exactly once: anything that sends, pays or orders goes through this
    def once(self, key: str, fn: Callable[[], Any]) -> Any:
        if key in self._done:
            self.append("once_skipped", key=key)
            return self._done[key]
        result = fn()
        self._done[key] = result
        self.append("once", key=key, result=result)
        return result


# ---- response cache, shared across runs. Keyed by the request, not the run.
def cache_get(key: str) -> Optional[Any]:
    _ensure()
    p = CACHE / f"{key}.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return None


def cache_put(key: str, value: Any) -> None:
    _ensure()
    (CACHE / f"{key}.json").write_text(json.dumps(value, default=str), encoding="utf-8")
