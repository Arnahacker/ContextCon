"""One cached tool call to Claude. The only place in INVARIANT that talks to an LLM.

Lookup order:
  offline (INVARIANT_OFFLINE=1 or no ANTHROPIC_API_KEY):
      fixtures/llm/<hash>.json  ->  fixtures/llm/index.json[kind][key]  ->  LookupError
  live:
      data/llm_cache.sqlite  ->  Messages API (then stored in sqlite and fixtures/llm/<hash>.json)
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "fixtures" / "llm"
CACHE_DB = ROOT / "data" / "llm_cache.sqlite"

# Claude Opus 5.5 is the current default model. Note for CLAUDE.md rule 10: on this model
# forced tool_choice ("any"/"tool") and `temperature` both return 400, so we use
# tool_choice auto + strict schema + a prompt that requires the tool, and rely on the
# request-hash cache (plus the deterministic normalizer) for repeatability.
MODEL = os.environ.get("INVARIANT_LLM_MODEL", "claude-opus-5-5")
TIMEOUT_S = float(os.environ.get("INVARIANT_LLM_TIMEOUT", "30"))

log = logging.getLogger("invariant.read")

# where the last call_tool answer came from: "fixture" | "cache" | "claude"
last_source: str | None = None


class LLMUnavailable(LookupError):
    """No fixture offline, or the live call failed. Callers fall back to rules."""


def offline() -> bool:
    return os.environ.get("INVARIANT_OFFLINE") == "1" or not os.environ.get("ANTHROPIC_API_KEY")


def request_hash(prompt_version: str, text: str) -> str:
    return hashlib.sha256(f"{MODEL}\n{prompt_version}\n{text}".encode()).hexdigest()


def _index() -> dict:
    p = FIXTURES / "index.json"
    return json.loads(p.read_text()) if p.exists() else {}


def _db() -> sqlite3.Connection:
    CACHE_DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(CACHE_DB)
    con.execute("CREATE TABLE IF NOT EXISTS llm_cache (key TEXT PRIMARY KEY, model TEXT, response TEXT)")
    return con


def call_tool(*, kind: str, index_key: str, prompt_version: str, system: str, tool: dict,
              user_text: str) -> dict[str, Any]:
    """Return the raw tool input for one request. `kind` + `index_key` address index.json."""
    global last_source
    key = request_hash(prompt_version, user_text)
    fixture = FIXTURES / f"{key}.json"
    if offline():
        last_source = "fixture"
        if fixture.exists():
            return json.loads(fixture.read_text())
        idx = _index().get(kind, {})
        if index_key in idx:
            return idx[index_key]
        raise LLMUnavailable(f"offline: no LLM fixture for {kind} {index_key!r} (hash {key})")

    with _db() as con:
        row = con.execute("SELECT response FROM llm_cache WHERE key = ?", (key,)).fetchone()
    if row:
        last_source = "cache"
        return json.loads(row[0])
    import anthropic

    try:
        out = _live(system=system, tool=tool, user_text=user_text)
    except (anthropic.APIConnectionError, anthropic.APIStatusError, RuntimeError) as exc:
        # APIConnectionError covers timeouts; APIStatusError covers 4xx/5xx incl. auth
        raise LLMUnavailable(f"live LLM call failed for {kind}: {type(exc).__name__}: {exc}") from exc
    last_source = "claude"
    with _db() as con:
        con.execute("INSERT OR REPLACE INTO llm_cache VALUES (?, ?, ?)", (key, MODEL, json.dumps(out)))
    FIXTURES.mkdir(parents=True, exist_ok=True)
    fixture.write_text(json.dumps(out, indent=1, ensure_ascii=False))  # replayable offline
    return out


def _live(*, system: str, tool: dict, user_text: str) -> dict[str, Any]:
    import anthropic  # imported lazily so offline runs never need the SDK configured

    client = anthropic.Anthropic(timeout=TIMEOUT_S, max_retries=1)
    messages = [{"role": "user", "content": user_text}]
    for _ in range(2):  # tool_choice auto does not guarantee a call: re-ask once
        resp = client.beta.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=system,
            tools=[{**tool, "strict": True}],
            tool_choice={"type": "auto"},
            output_config={"effort": "low"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            messages=messages,
        )
        if resp.stop_reason == "refusal":
            raise RuntimeError(f"LLM refused: {getattr(resp, 'stop_details', None)}")
        for block in resp.content:
            if block.type == "tool_use" and block.name == tool["name"]:
                return dict(block.input)
        messages = messages + [
            {"role": "assistant", "content": resp.content},
            {"role": "user", "content": f"Call the {tool['name']} tool now. Do not answer in text."},
        ]
    raise RuntimeError(f"LLM did not call {tool['name']}")


def nullable(t: str) -> dict:
    return {"anyOf": [{"type": t}, {"type": "null"}]}
