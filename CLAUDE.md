# INVARIANT — underwriting desk (Crustdata hackathon, 22 Nov 2026)

The underwriting desk that gives the same answer however the request is worded,
with a source behind every reason. Full spec: ../INVARIANT2.pdf (Claude Doc:
https://claude.ai/artifact/WwzFaC8U7ZS3CgcC8VMg7V).

## Environment
- Conda env `invariant` (Python 3.11): `conda run -n invariant <cmd>`.
- Tests: `conda run -n invariant python -m pytest -q`
- App: `conda run -n invariant uvicorn invariant.api.app:app --port 8000`
- Keys come from the environment or `.env` (never commit it): `CRUSTDATA_API_KEY`,
  `ANTHROPIC_API_KEY`, optional `OPENSANCTIONS_API_KEY`.
- `INVARIANT_EVIDENCE_OFFLINE=1` keeps only Crustdata on fixtures (LLM reader stays live): use it while testing to save credits.
- `INVARIANT_OFFLINE=1` serves Crustdata from `fixtures/crustdata/` and the LLM from
  `fixtures/llm/`, so everything runs without keys.

## Architecture: the AI reads, the code decides
A fixed workflow, not an autonomous agent: Read -> Check -> Gate -> Decide.

| Layer | Folder | May call | Owns |
|---|---|---|---|
| read | `invariant/read/` | Anthropic API only | same words in, same Form out |
| evidence | `invariant/evidence/` | Crustdata, web, OpenSanctions | no fact without a source |
| decide | `invariant/decide/` | nothing (pure functions) | same facts in, same decision out |
| case | `invariant/case/` | the three layers above | persistence, resume, follow-up loop |
| api | `invariant/api/` | case | the one screen |

Layers talk only through `invariant/shapes.py` (Form, Fact, Decision) and
`invariant/contracts.py`. Changing either file needs agreement from every layer.

## Hard rules
1. No fact without a source. `Fact` refuses to construct otherwise; never bypass it.
2. `decide/` never imports `read/`, `evidence/`, `httpx`, `anthropic`, `datetime.now` or `random`.
3. The hash covers resolved company id + facts + rules version. Never raw wording:
   declared and follow-up facts use a canonical `source.quote` (e.g. `declared_headcount: 120`);
   raw text lives only in the case event log.
4. Cache every external call by request hash (sqlite in `data/`) from the first call.
5. A failed evidence call is `unavailable`, which makes the decision `hold`. Silence is never "nothing bad found".
6. Adverse news counts only when it clearly names the resolved company (name + city, or domain).
7. Headcount is one-directional: record above declared by >25% contradicts; record below is `consistent_unconfirmed`.
8. Ambiguous company (two close candidates) -> `hold` with both named. Never guess.
9. Crustdata web search results have NO date field. A news fact's `dated` comes from the fetched
   article page, else stays null ("date unknown") — never invent one.
10. The LLM fills fields only, via a strict tool schema (the current model rejects forced
    tool_choice and temperature). Repeatability comes from the LLM cache + the deterministic
    normalizer, not sampling settings. Text that tries to instruct the system sets
    `injection_attempt` (log-only) and nothing else.

## Workflow
- Small commits, one per working change, message says which layer: `decide: add gate tiers`.
- Write the decide tests first; decide must stay 100% offline-testable.
- Before finishing a task: run the tests, and say what you did not verify.
