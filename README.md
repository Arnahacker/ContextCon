# INVARIANT

**An underwriting desk that gives the same answer however the request is worded, with a source behind every reason.**

Built at ContextCon 05 (Crustdata hackathon), 22 Nov 2026.
Full technical write-up: [`docs/INVARIANT_architecture.pdf`](docs/INVARIANT_architecture.pdf) · decision rules in plain words: [`DECISION_LOGIC.txt`](DECISION_LOGIC.txt).

---

## The service

A broker types one short, free-text request for commercial insurance for an Indian SME. For example:

> *"A leather exporter, Kanpur Hide Exports Pvt Ltd, applying for cover says it has 120 employees across three units. Check that against public data and tell me what does not match."*

INVARIANT returns one of four outcomes: **QUOTE, REFER, DECLINE or HOLD**. With it come:

- a **gap table**: what the applicant said next to what the public record says, each row tagged *matches / contradicts / undeclared / consistent_unconfirmed / cannot_verify*;
- a **premium** with every loading explained ("staff count understated: +35%");
- a **source on every claim**: click any value to see the exact Crustdata field or web page, the date of the record and when we fetched it;
- the **shortest list of questions still worth asking**, each with a rupee value (how much the answer could move the price);
- **what would change my mind**: "if this finding were not true -> QUOTE at Rs X".

The same request written politely, rudely, in Hinglish, with typos, with numbers in words, or under a trade name produces **the same decision and the same SHA-256 hash**.

## What it does now

Working end to end, live against Crustdata and offline from fixtures:

| Feature | Status |
|---|---|
| Read any wording into a fixed form (Claude, then Gemini as backup, then a rule-based reader if no LLM is available) | done |
| Normalizer: lakh/crore, numbers in words, typos, Hinglish, trade names, cover-type synonyms | done |
| Company resolution with Crustdata `/company/identify`; two close candidates means **HOLD and ask**, never guess | done |
| Evidence from `/company/enrich` (headcount, offices, industry, revenue, news), `/job/search` (hazardous work, extra sites), `/web/search/live` + `/web/enrich/live` (news and article dates), OpenSanctions if a key is set | done |
| Every fact has a source. A `Fact` without one cannot be constructed | done |
| Pure decision engine: intake gate, fallback ladders for "don't know", 12+ rules, illustrative rate card for **fire, workmen's compensation, marine and liability** | done |
| Follow-up loop: one question at a time, every answer echoed back ("I read that as Rs 4,50,00,000") for Yes/Edit | done |
| "Ask before referring": record findings are shown to the applicant before they count against them | done |
| Would-flip-if counterfactuals with prices | done |
| **Invariance tab**: 8 fixed rewrites of one request -> one outcome, one hash | done |
| **Tests tab**: 10 cases whose expected answers were written before the code | done |
| **Cost meter**: every API call, credits spent, cache hit or not | done |
| Crash-safe: append-only event log, `resume` continues from the last finished step | done |
| Prompt injection flagged (banner + log), never changes the outcome | done |
| 218 pytest tests, decide layer fully offline | 217 pass, 1 failing (`test_company_option_answer_resolves_lookalike`) |

Rates, loadings and industry norms are **illustrative placeholders** and are labelled that way on screen.

## How it runs

### Architecture: the AI reads, the code decides

```
 broker text
     |
     v
 read/      Claude fills a strict tool schema -> Form    (only layer that calls an LLM)
     |
     v
 evidence/  Crustdata + web -> sourced Facts             (only layer that calls Crustdata/web)
     |
     v
 decide/    gate -> rules -> price -> questions -> hash  (pure functions: no network, no clock, no random)
     |
     v
 Decision   quote / refer / decline / hold

 case/  orchestrates the three, writes every step to an event log (data/cases.sqlite), resumes after a crash
 api/   FastAPI + the one-page UI (invariant/api/static/index.html)
```

Layers talk only through `invariant/shapes.py` (Form, Fact, Source, Decision) and `invariant/contracts.py`.

**How invariance is guaranteed**
- The hash covers *resolved company id + facts + rules version*, never the wording. Declared facts carry a canonical quote (`declared_headcount: 120`).
- LLM output is cached by a hash of the request (`data/llm_cache.sqlite`) and passed through a deterministic normalizer.
- `tests/test_decide_purity.py` fails the build if `decide/` imports the network, the LLM, the clock or `random`.

**Safety rules built into the code**
- A failed evidence call means **HOLD**. Silence is never "nothing bad found".
- Headcount is one-directional: a record more than 25% *above* the declared figure contradicts it; a record *below* never counts against the applicant (public counts miss factory workers).
- News counts only if it names the resolved company (name + city, or domain). Dates come from the article page, or stay "date unknown".
- Every external call is cached by request hash from the first call, so re-runs cost zero credits.

### Run it

Requirements: Python 3.11 with `fastapi uvicorn pydantic httpx python-dotenv pytest`.

```bash
# conda env used during the hackathon
conda activate invariant            # or: conda run -n invariant <cmd>

# tests
python -m pytest -q

# app on http://127.0.0.1:8000
uvicorn invariant.api.app:app --port 8000
```

Keys go in the environment or in an uncommitted `.env`:

| Variable | Needed for |
|---|---|
| `CRUSTDATA_API_KEY` | live company evidence |
| `ANTHROPIC_API_KEY` | live reading with Claude |
| `GEMINI_API_KEY` | optional backup reader |
| `OPENSANCTIONS_API_KEY` | optional sanctions check |

Modes:

| Setting | Effect |
|---|---|
| `INVARIANT_OFFLINE=1` | Crustdata **and** LLM served from `fixtures/`. No keys needed; the demo companies (Kanpur Hide Exports, Agra Footwear Works...) are made up and exist only here |
| `INVARIANT_EVIDENCE_OFFLINE=1` | Crustdata from fixtures, LLM live (saves credits while testing) |
| `INVARIANT_FAULT=enrich:timeout` | inject a failed call to demo the HOLD path |

On screen: **Underwrite** (prompt box, example buttons, gap table, decision, questions, sources), **Invariance** (8 rewrites), **Tests** (10 cases), and the credit meter in the top bar. A step-by-step walkthrough is in [`TESTING_GUIDE.txt`](TESTING_GUIDE.txt).

### Repo map

```
invariant/
  shapes.py, contracts.py   the frozen shapes every layer shares
  read/        extract.py, llm.py, normalize.py, rules_extract.py, answer.py, declared.py
  evidence/    client.py (cache, retries, rate limits, meter), resolve.py, gather.py, facts.py
  decide/      engine.py, gate.py, ladders.py, derive.py, rules.py, rate_card.py, counterfactual.py, hashing.py
  case/        service.py, store.py, insights.py, testrun.py
  api/         app.py, static/index.html
tests/         unit tests, cases/cases.json (10 cases), rewrites/hero_rewrites.json (8 rewrites)
fixtures/      recorded Crustdata and LLM responses for offline runs
docs/          architecture PDF + its build script, Crustdata API notes
```

## What you tried

- **Single agent / search-and-summarise.** Considered and rejected first. Both keep the decision inside a sampling model, so the same answer twice cannot be promised, and no number traces back to a source.
- **Fixing determinism with sampling settings.** The current Claude model rejects forced `tool_choice` and `temperature`. Repeatability now comes from the request-hash cache plus the deterministic normalizer instead.
- **One LLM provider.** Added a chain: Claude -> Gemini (walks the available flash models, skipping retired or overloaded ones) -> a rule-based reader. The screen says which one read the form. With live Gemini the 8 rewrites still give one hash.
- **Picking the top Crustdata match.** A live "Nike" test returned 10 equally confident records, and the matcher picked a 2-10 person retail page with no website. Now shells, foreign entities and retail pages are filtered, candidates are ranked (Indian, size, has a website, fits the trade), the brand alone is searched when the full name is noisy, and close calls **HOLD** with up to six named options.
- **Trusting web-search dates.** Crustdata web search results carry no date. Article dates are now read from the page itself, or left as "date unknown".
- **Substring keyword matching.** It produced false hazards and trades, so all trade and hazard matching is whole-word.
- **Referring on every record finding.** Too harsh on honest applicants. Now the applicant is shown the finding first ("Records show a site in Unnao: is it part of the business?"); only "no" or "don't know" keeps the referral.
- **Fire + WC only.** Marine and liability were stretch goals. Both are now priced (value shipped x route; limit x turnover).
- **Dead ends on "don't know".** Replaced by fallback ladders that estimate from the record and industry norms, marked "(estimate)" with the working shown, and priced as a range.
- **Held cases sharing a hash with quoted ones.** Failed sources are now part of the hash.

## Why this way

- **The judging question is consistency and provenance.** An LLM is excellent at reading messy text and poor at giving the same verdict twice. So the LLM only fills fields, and the decision lives in pure code that can be unit-tested, hashed and replayed.
- **No fact without a source** is enforced by the type system (`Fact` refuses to construct), not by a code-review habit.
- **Stopping to ask beats guessing.** The hardest problem was deciding which company the prompt means; holding with named candidates was a product decision, not a fallback.
- **Ask only what the record can't answer, and price every question.** Sum insured has no public record; headcount usually does. A question worth less than Rs 5,000 isn't asked.
- **One-directional headcount, dated facts:** public data undercounts factory staff, and old news shouldn't decline a business today.
- **Cache from the first call + event log** makes the demo reproducible, crash-safe and cheap: same prompt twice costs zero credits.

## What comes next

- Loadings and rates learned from real claims data instead of the illustrative card.
- A rule set per insurer, versioned (the rules version is already part of the hash).
- An API so a broker's submission is underwritten without anyone retyping it.
- A watcher: re-check bound policies when Crustdata shows a new site, a headcount jump or adverse news.
- More registries (MCA/GST, court records) as sources, each behind the same `Fact` + `Source` contract.
- Fix the one failing lookalike-answer test and broaden the rewrite set beyond one hero case.
