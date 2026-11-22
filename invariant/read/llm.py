"""One cached structured-output call to an LLM. The only place in INVARIANT that talks to one.

Providers, tried in order (INVARIANT_LLM_PROVIDERS, default "claude,gemini"); a provider is
used only when its key is set (ANTHROPIC_API_KEY / GEMINI_API_KEY):
  claude : Messages API, strict tool schema (forced tool_choice/temperature are rejected
           by the current model, so the prompt requires the tool call)
  gemini : generateContent REST, temperature 0, JSON-schema response

Lookup order:
  INVARIANT_OFFLINE=1, or no provider key:
      fixtures/llm/<hash>.json -> fixtures/llm/index.json[kind][key] -> LLMUnavailable
  live:
      data/llm_cache.sqlite -> each provider in order -> LLMUnavailable
      (a live answer is cached + written to fixtures/llm/<hash>.json, so the same text is
       always read the same way afterwards, whichever provider first read it)
Callers fall back to the rule-based reader on LLMUnavailable.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "fixtures" / "llm"
CACHE_DB = ROOT / "data" / "llm_cache.sqlite"

MODEL = os.environ.get("INVARIANT_LLM_MODEL", "claude-opus-5-5")  # Claude model
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
TIMEOUT_S = float(os.environ.get("INVARIANT_LLM_TIMEOUT", "30"))

log = logging.getLogger("invariant.read")

# where the last call_tool answer came from: "fixture" | "cache" | "claude" | "gemini"
last_source: str | None = None
# which provider originally produced it: "claude" | "gemini" | "fixture"
last_provider: str | None = None


class LLMUnavailable(LookupError):
    """No fixture offline, or every live provider failed. Callers fall back to rules."""


def providers() -> list[str]:
    order = [p.strip() for p in os.environ.get("INVARIANT_LLM_PROVIDERS", "claude,gemini").split(",") if p.strip()]
    keys = {"claude": "ANTHROPIC_API_KEY", "gemini": "GEMINI_API_KEY"}
    return [p for p in order if p in keys and os.environ.get(keys[p])]


def offline() -> bool:
    return os.environ.get("INVARIANT_OFFLINE") == "1" or not providers()


def request_hash(prompt_version: str, text: str) -> str:
    # provider-independent on purpose: one text is read once, then always read the same way
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
    """Return the raw structured output for one request. `kind` + `index_key` address index.json."""
    global last_source, last_provider
    key = request_hash(prompt_version, user_text)
    fixture = FIXTURES / f"{key}.json"
    if offline():
        last_source = last_provider = "fixture"
        if fixture.exists():
            return json.loads(fixture.read_text())
        idx = _index().get(kind, {})
        if index_key in idx:
            return idx[index_key]
        raise LLMUnavailable(f"offline: no LLM fixture for {kind} {index_key!r} (hash {key})")

    with _db() as con:
        row = con.execute("SELECT model, response FROM llm_cache WHERE key = ?", (key,)).fetchone()
    if row:
        last_source = "cache"
        last_provider = "gemini" if str(row[0]).startswith("gemini") else "claude"
        return json.loads(row[1])

    errors = []
    for provider in providers():
        try:
            if provider == "claude":
                out, model = _live_claude(system=system, tool=tool, user_text=user_text), MODEL
            else:
                out, model = _live_gemini(system=system, tool=tool, user_text=user_text)
        except Exception as exc:  # any provider failure: try the next one, then rules
            errors.append(f"{provider}: {type(exc).__name__}: {str(exc)[:200]}")
            log.warning("read: %s failed for %s: %s", provider, kind, errors[-1])
            continue
        last_source = last_provider = provider
        with _db() as con:
            con.execute("INSERT OR REPLACE INTO llm_cache VALUES (?, ?, ?)", (key, model, json.dumps(out)))
        FIXTURES.mkdir(parents=True, exist_ok=True)
        fixture.write_text(json.dumps(out, indent=1, ensure_ascii=False))  # replayable offline
        return out
    raise LLMUnavailable(f"every LLM provider failed for {kind}: {'; '.join(errors)}")


# ------------------------------------------------------------------ claude


def _live_claude(*, system: str, tool: dict, user_text: str) -> dict[str, Any]:
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


# ------------------------------------------------------------------ gemini

_gemini_model: str | None = None


def _gemini_post(model: str, body: dict) -> httpx.Response:
    return httpx.post(f"{GEMINI_BASE}/models/{model}:generateContent", json=body, timeout=TIMEOUT_S,
                      headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]})


def _gemini_pick_model() -> str:
    """The configured model if it exists, else the newest available 'flash' model."""
    r = httpx.get(f"{GEMINI_BASE}/models", timeout=TIMEOUT_S, params={"pageSize": 200},
                  headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]})
    r.raise_for_status()
    names = [m["name"].split("/", 1)[1] for m in r.json().get("models", [])
             if "generateContent" in m.get("supportedGenerationMethods", [])]
    if GEMINI_MODEL in names:
        return GEMINI_MODEL
    flash = sorted((n for n in names if "flash" in n and "lite" not in n and "image" not in n
                    and "tts" not in n and "exp" not in n), reverse=True)
    if not flash:
        raise RuntimeError(f"no usable Gemini flash model in {names[:10]}")
    log.warning("read: Gemini model %s not available, using %s", GEMINI_MODEL, flash[0])
    return flash[0]


def _live_gemini(*, system: str, tool: dict, user_text: str) -> tuple[dict[str, Any], str]:
    global _gemini_model
    if _gemini_model is None:
        _gemini_model = _gemini_pick_model()
    schema = tool["input_schema"]
    instruction = (f"{system}\n\nReturn ONLY a JSON object for `{tool['name']}`: "
                   f"{tool.get('description', '')}")
    body = {
        "systemInstruction": {"parts": [{"text": instruction}]},
        "contents": [{"role": "user", "parts": [{"text": user_text}]}],
        "generationConfig": {"temperature": 0, "responseMimeType": "application/json",
                             "responseJsonSchema": schema},
    }
    r = _gemini_post(_gemini_model, body)
    if r.status_code == 400:  # schema keyword not accepted: describe it in the prompt instead
        body["generationConfig"].pop("responseJsonSchema")
        body["systemInstruction"]["parts"][0]["text"] += "\nJSON schema:\n" + json.dumps(schema)
        r = _gemini_post(_gemini_model, body)
    r.raise_for_status()
    data = r.json()
    cands = data.get("candidates") or []
    if not cands:
        raise RuntimeError(f"Gemini returned no candidates: {json.dumps(data.get('promptFeedback'))[:200]}")
    text = "".join(p.get("text", "") for p in cands[0].get("content", {}).get("parts", []))
    out = json.loads(text)
    if not isinstance(out, dict):
        raise RuntimeError("Gemini did not return a JSON object")
    allowed = set(schema.get("properties", {}))
    return {k: v for k, v in out.items() if k in allowed}, _gemini_model


def nullable(t: str) -> dict:
    return {"anyOf": [{"type": t}, {"type": "null"}]}
