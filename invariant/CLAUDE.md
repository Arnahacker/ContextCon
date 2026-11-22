# INVARIANT — context for Claude Code

Hackathon build (Crustdata @ ContextCon 5.0, BITS Pilani). Team of 4.
**Demo at 18:00 IST on 22 Nov 2026. Code freeze 17:45.**

## What it is

An automated commercial underwriting desk for Indian SME insurance. A broker
types two lines of plain text. We work out which company it is, check every
claim against public records, ask only what no record can answer, and return a
priced decision where every reason links to a dated source.

The pitch, and the judging line we are built to answer:
*the same decision however the request is worded, with a source behind every reason.*

Sample input, from the hackathon page:
> A leather exporter applying for cover says it has 120 employees across three
> units. Check that against public data and tell me what does not match.

Input is ALWAYS a short prompt. No PDF, no email, no file upload.

## The one rule everything rests on

**The AI reads. The code decides.**

1. `read_step.py` — a model fills a small fixed form. No opinions, no prices,
   no reasoning. Temperature 0.
2. `build.py` / `identity.py` — evidence becomes `Fact` objects.
3. `decide.py` — `decide(facts, rules) -> Decision`. A **pure function**.

### Invariants. Breaking any of these breaks the product's whole claim.

- **Never import anything with side effects into `decide.py`.** No httpx, no
  model calls, no clock, no randomness, no file reads. If you need data there,
  pass it in. This purity is what makes the invariance panel, "what would
  change my mind" and the priced question list possible at all.
- **A `Fact` cannot exist without a source.** Enforced in the constructor in
  `facts.py`. Only `cannot_verify` may be sourceless. Do not add a bypass.
- **The decision hash covers the facts and the rules version only** — never the
  wording, never the order answers arrived in.
- **Derived values price, but never clear the gate and never cause a decline.**
  `resolved()` in `decide.py` skips `origin == "derived"`.
- **Headcount is one-directional.** Record far ABOVE declared = `contradicts`.
  Record at or below declared = `consistent_unconfirmed`, never a mismatch:
  public profiles undercount factory floors.
- **An empty search result is a fact (`search_negative`), a timed-out search is
  `cannot_verify` and holds.** Silence is never "nothing bad found".
- **Never invent a finding to look thorough.** A wrong fact costs more than a
  missed one — this is explicit in the judging criteria. See the comment in
  `adapt.sites()` for a case where we deliberately report less.
- **Always pass `encoding="utf-8"`** to `read_text` / `write_text` / `open`.
  The team is on Windows; the default is cp1252 and it mangles ₹.

## Run it

```bash
pip install -r requirements.txt
cp .env.example .env        # Windows: copy .env.example .env
./run.sh                    # Windows: run.bat      -> localhost:8000
pytest -q                   # 65 tests, no network
```

With no keys it runs end to end on `mocks/*.json` with a regex reader.
`.env` is loaded by `invariant/__init__.py`, not the shell.

## Repo map

```
invariant/
  schemas.py    Form, Decision, Question, Step. Frozen contract - tell the team before changing.
  facts.py      Fact + Source. The no-source-no-fact rule lives here.
  normalize.py  lakh/crore, numbers in words, Hindi numerals, name canonicalising.
                Invariance is won or lost in this file.
  read_step.py  step 1. backends: anthropic (real) | stub (regex, tests only).
  identity.py   the 3-rung ladder. rung 0 named -> identify. rung 1 narrow by
                industry. rung 2 no identity -> check the CLASS not the company.
  adapt.py      unwraps the REAL Crustdata v2 response. Verified live 22 Nov.
  build.py      API responses -> Facts.
  decide.py     step 3. PURE. Read the invariants above before touching.
  rules.yaml    illustrative rate card, tolerances, gate tiers, loadings, discounts.
  assume.py     derived stand-ins so a blocked case still shows a number.
  explain.py    "what would change my mind" + priced questions. Both re-run decide().
  summary.py    plain English for the screen. Deterministic - no model.
  pipeline.py   Read -> Check -> Decide, wired together.
  app.py        FastAPI. /api/run /api/invariance /api/tests /api/approval
  static/       the one screen, three tabs.
  runlog.py     append-only log, response cache, exactly-once.
  ledger.py     credits per call. budget.py: per-run ceiling -> HOLD, never crash.
  approvals.py  nothing irreversible leaves without a click.
  rewrites.py   the 8 fixed wordings. cases.py: golden cases.
  examples.py   on-screen examples, each verified live; replayed offline from
                mocks/by_request/. Re-record them when you change a request body.
  gst.py        what a GSTIN proves about itself: check digit, legal form, state.
                Never that it belongs to the company (that needs the GST portal).
```

## Crustdata, as it really behaves

Base `https://api.crustdata.com`, headers `authorization: Bearer <key>` and
`x-api-version: 2025-11-01`.

- Response envelope is a **LIST**: `[{matched_on, match_type, matches:
  [{confidence_score, company_data}]}]`. Not `{"companies": [...]}`.
- Identifiers are **plural arrays**, one type per call: `names`, `domains`,
  `crustdata_company_ids`.
- `/company/enrich` returns `basic_info` ONLY unless you list sections in
  `fields`: headcount, locations, taxonomy, hiring, people, news...
- `basic_info.description` often names certifications (ISO 14001, SA8000,
  BSCI, WRAP) — that is where the discount evidence comes from, free.
- `headcount.growth_percent.yoy` is pre-computed. Do not recompute it.
- `headcount.by_region_absolute` keys overlap at several granularities
  ("Greater Kolkata Area", "Rajarhat", "West Bengal, India" are one place).
  Never count them as sites. Only a recognised foreign country counts.
- Rate limits: web 10/min, enrich 15/min. **Cache everything** — already done
  in `evidence/crustdata.py`, keyed by request hash.

- `/job/search` returns a DICT `{job_listings, next_cursor, total_count}`.
  Filter on `company.basic_info.crustdata_company_id` (`company_id` is a 400).
  A fuzzy `(.)` name filter returns OTHER companies' jobs - filter by id only.
  Some listings carry a null company id; `adapt.jobs()` drops them.
- `/web/search/live` returns `{success, query, timestamp, results, metadata}`;
  each web result is `{position, title, snippet, url, source}` - no date, and
  the url is often a google.com/goto redirect. No `limit` param.
- Cost comes back in the `x-credits-used` header. `/company/search` is the
  expensive one (~7.6 credits for a 25-row class check).
- `/company/identify` returns DUPLICATE profiles of one company with equal
  scores, and plant-level profiles ("...Limited, Roha And Mahad") that can
  outscore the company. `identity.break_tie` / `exact_name_match` resolve only
  same-company duplicates or an exact match for the name given; anything else
  still holds. The committed `company_identify.json` mock is trimmed: live
  Rajda returns four Rajdas tied at 0.80.
- Mock and live use SEPARATE cache namespaces. They used to share one, and the
  fake company_search mock was served as live evidence. Real responses for the
  on-screen examples are in `mocks/by_request/` (keyed by request hash), so
  mock mode shows the right company for each example.

Verified live: `/company/identify`, `/company/enrich`, `/job/search`,
`/web/search/live` (22 Nov). Real responses are in `mocks/`.

## Covers and inputs

- Covers live in `rules.yaml -> covers`: fire, burglary, marine_cargo, wc. Each
  names its basis (sum insured / annual shipments / annual wages), its rate
  table, and what it `needs` before it can be priced. `decide.py` reads them;
  a loading with `applies_to` only fires on those covers.
- A broker can give a company name, a website (identified by domain first,
  exact) or a GSTIN.
- Read step: **Gemini** when GEMINI_API_KEY is set (google-genai SDK, JSON
  output against FORM_JSON_SCHEMA, temperature 0, fixed seed; model from
  GEMINI_MODEL, default gemini-2.5-flash). Claude (`claude-opus-5-5`) is kept
  as a second backend. READ_MODEL only applies to the backend it names.

## Findings we deliberately do NOT make (each was wrong on live data)

- Staff abroad (`staff_abroad`) and hiring abroad (`hiring_abroad`) are
  context, never an undeclared site: a sales office is not premises.
- A job city is an undeclared site only if it is in the home country, is a
  different city (compared by city name, aliases folded: Bangalore=Bengaluru),
  and takes the count past the sites declared. Otherwise `hiring_location`.
- Job listings older than 12 months are not evidence (`stale_job_listings`).
- A web result is an adverse event only if it names the company, the city AND
  an incident word. Directory and vendor pages name companies all the time.
- A declared industry is not an "undeclared hazard" of the same thing.

## Who owns what

- **A** reading and proving: read_step, normalize, rewrites, cases, tests tab.
- **B** evidence: crustdata client, adapt, identity, build.
- **C** deciding: decide, rules.yaml, explain, assume.
- **D** product: app, static, approvals, the demo.

## State, and what to do next

Working: all 3 rungs, gate, priced questions, what-would-change-my-mind,
certifications as discounts, one-directional headcount, lookalike hold,
timeout hold, injection resistance, exactly-once, credit ledger, budget
ceiling, 8/8 invariance on the stub reader, 6/6 golden cases, 16 unit tests.

Next, in order:
1. Real `CRUSTDATA_API_KEY`, then fix `/job/search` and `/web/search/live`
   parsing against actual responses.
2. Real `ANTHROPIC_API_KEY`, then re-run the Invariance tab. It must stay at
   one hash with a real model reading. **Never demo invariance on the stub.**
3. `evidence/site.py` — fetch the applicant's own website (/about,
   /infrastructure, /products, /certifications). Their own page contradicting
   their own form is the strongest finding we can produce.
4. `people/search` on safety/EHS titles — presence or absence of a safety
   officer at a site of this size is a real rating factor.
5. Watcher on bind (simulated webhook is fine).

Cut in this order if behind: watcher -> people search -> shortest-question
search -> UI polish. **Never cut:** a source on every fact, the invariance
panel, the tests tab, "I can't verify", the intake gate.

## Working style for this repo

- Run `pytest -q` after every change. It is fast and has no network.
- When something looks wrong on screen, ask whether a test could have caught
  it, and add that test. Three real bugs so far were invisible to a green suite.
- Prefer adding a golden case over adding a print statement.
- Commit every 30 minutes. Judges read commit history.
- Do not silently widen a rule to make a test pass. If the honest answer is
  "we cannot verify this", that is the feature, not a failure.
