# INVARIANT

The underwriting desk that gives the same answer however the request is worded,
with a source behind every reason.

**macOS / Linux**
```bash
pip install -r requirements.txt
cp .env.example .env          # put your keys in, or leave blank to run on mocks
./run.sh                      # http://localhost:8000
pytest -q                     # 16 tests, no network needed
```

**Windows (cmd)** — see WINDOWS.md
```cmd
pip install -r requirements.txt
copy .env.example .env
run.bat
pytest -q
```

`.env` is read by `invariant/__init__.py`, not by the shell, so keys load the
same way on every platform.

With no keys it runs end to end on `./mocks/*.json` and the stub reader, so all
four of you can build before anyone has a key.

## What is already here

```
invariant/
  schemas.py      the three frozen shapes: Form, Decision, Question, Step
  facts.py        Fact + Source. A fact CANNOT exist without a source: the
                  constructor raises. This is the whole "sourced claims" rule.
  normalize.py    lakh/crore, numbers in words, name and industry canonicalising.
                  Invariance is won or lost here.
  read_step.py    STEP 1. Model fills the form. Nothing else. Two backends:
                  anthropic (real) and stub (regex, for tests).
  identity.py     the three-rung ladder. Code picks the company, never the model.
  evidence/
    crustdata.py  cached, metered client. mock mode built in.
  build.py        API responses -> Facts. One-directional headcount rule,
                  same-company gate on adverse news, search-negative facts.
  decide.py       STEP 3. decide(facts, rules) -> Decision. PURE. No network,
                  no model, no clock. Same facts in, same hash out.
  assume.py       derived stand-ins so a blocked case still shows a number.
                  Derived values price, but never clear the gate or decline.
  explain.py      "what would change my mind" and the priced question list.
                  Both are just re-runs of decide().
  rules.yaml      illustrative rate card, tolerances, gate tiers, loadings.
  rewrites.py     the eight fixed wordings.
  cases.py        golden cases with answers written before the code.
  pipeline.py     Read -> Check -> Decide, wired together.
  app.py          FastAPI. /api/run /api/invariance /api/tests /api/approval
  static/         the one screen, three tabs.
  runlog.py       append-only log + response cache + exactly-once.
  ledger.py       every call, its credits, cached or live.
  budget.py       per-run time and credit ceiling. Hitting it HOLDS, never crashes.
  approvals.py    nothing irreversible leaves without a click.
tests/            16 tests. Keep decide.py testable with no network.
mocks/            fake Crustdata responses so nobody is blocked.
```

## The five rules the brief judges, and where each lives

| Rule | File |
|---|---|
| Decisions on live data | `evidence/crustdata.py`, `ledger.live_calls` |
| A source for every claim | `facts.py` — enforced in the constructor |
| A person approves the irreversible | `approvals.py` |
| A ceiling on every run | `budget.py` + `ledger.py` |
| Survives a crash or a timeout | `runlog.py` — `once()` and the cache |

## Known and deliberate

**The invariance panel currently shows 2 distinct hashes, not 1.** The stub
reader misses "three separate manufacturing units", "teen units" and "3
production sites". That is the panel doing its job: it is a detector, not a
decoration. Put a real key in `.env` and the model should take it to 1. **Never
demo invariance on the stub** — a regex that ignores wording proves nothing.

`occupancy` is taken from the applicant's words before the record. If job ads
prove tanning, occupancy should be upgraded and is not yet. Small fix in
`pipeline.py`.

## Next, in order

1. Real `ANTHROPIC_API_KEY` and `CRUSTDATA_API_KEY`, then re-run the invariance tab.
2. `evidence/site.py` — fetch the applicant's own website (`/about`,
   `/infrastructure`, `/products`, `/certifications`). Highest value left on the
   table: their own page contradicting their own form, and certifications as
   discounts.
3. The follow-up conversation: `/api/run` already takes `answers`; wire the chat
   and the echo-back-and-confirm.
4. `people/search` on safety titles, and employee locations as a third route to
   undeclared sites.
5. Watcher on bind.
