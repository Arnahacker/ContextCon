"""The workflow: Read -> Check -> Gate/Decide, plus the follow-up question loop.

State is always rebuilt from the event log (see store.py), so any step can be
re-run after a crash. Evidence is gathered once per resolved company; answers
only re-run the pure Decide step.
"""
from __future__ import annotations

import re
from typing import Optional

from invariant.case import insights, store
from invariant.decide.breakdown import breakdown
from invariant.contracts import DecideInput, EvidenceResult, FieldReading
from invariant.decide.derive import derive
from invariant.decide.engine import decide
from invariant.evidence.gather import gather
from invariant.read.answer import followup_fact, read_answer
from invariant.read.declared import declared_facts
from invariant.read import extract_with_reader
from invariant.shapes import Decision, Fact, Form

# ------------------------------------------------------------------ state


def _state(case_id: str) -> dict:
    form = store.last(case_id, "form")
    ev = store.last(case_id, "evidence")
    created = store.events(case_id)[0]["at"]
    answers: list[Fact] = []  # every confirmed answer; a field asked twice keeps both (ladder rungs)
    pending: dict[str, dict] = {}
    for e in store.events(case_id):
        p = e["payload"]
        if e["kind"] == "answer_read":
            pending[p["field"]] = p
        elif e["kind"] == "answer_confirmed":
            answers.append(Fact.model_validate(p["fact"]))
            pending.pop(p["fact"]["field"], None)
        elif e["kind"] == "answer_rejected":
            pending.pop(p["field"], None)
        elif e["kind"] == "answer_confirmed_company":  # handled by re-gathering, not as a fact
            pending.pop("company", None)
    return {
        "form": Form.model_validate(form) if form else None,
        "evidence": EvidenceResult.model_validate(ev) if ev else None,
        "created": created,
        "answers": answers,
        "pending": pending,
    }


def _all_facts(st: dict) -> list[Fact]:
    facts = list(declared_facts(st["form"], st["created"]))
    facts += list(st["evidence"].facts)
    facts += st["answers"]
    # a real follow-up answer supersedes the declared claim for the same field
    answered = {f.field for f in st["answers"] if f.status != "cannot_verify"}
    return [f for f in facts if not (f.origin == "declared" and f.field in answered)]


def _decide(case_id: str, st: dict, extra: Optional[list[Fact]] = None) -> Decision:
    ev: EvidenceResult = st["evidence"]
    facts = _all_facts(st) if extra is None else extra
    return decide(
        DecideInput(
            resolution=ev.resolution,
            facts=facts,
            unavailable=list(ev.unavailable),
            # yes/no checks on record findings are not optional questions: they never use up the cap
            questions_asked=sum(1 for f in st["answers"] if not f.field.startswith("confirm_")),
            injection_attempt=st["form"].injection_attempt,
        )
    )


def _redecide(case_id: str) -> Decision:
    st = _state(case_id)
    d = _decide(case_id, st)
    store.append(case_id, "decision", d.model_dump(mode="json"))
    return d


# ------------------------------------------------------------------ steps


def run_case(prompt: str) -> str:
    """Create a case and run it to its first decision. Returns the case id."""
    case_id = store.new_case(prompt)
    resume(case_id)
    return case_id


def resume(case_id: str) -> Decision:
    """Run whatever steps are missing. Safe to call repeatedly."""
    while step(case_id):
        pass
    return Decision.model_validate(store.last(case_id, "decision"))


STAGES = ["read", "evidence", "decide"]


def next_stage(case_id: str) -> Optional[str]:
    if store.last(case_id, "form") is None:
        return "read"
    if store.last(case_id, "evidence") is None:
        return "evidence"
    if store.last(case_id, "decision") is None:
        return "decide"
    return None


def step(case_id: str) -> Optional[str]:
    """Run exactly one missing stage, so the screen can show real progress.
    Returns the stage that ran, or None when the case was already complete."""
    stage = next_stage(case_id)
    if stage is None:
        return None
    if stage == "read":
        prompt = store.events(case_id)[0]["payload"]["text"]
        form, reader = extract_with_reader(prompt)
        store.append(case_id, "form", form.model_dump(mode="json"))
        store.append(case_id, "reader", {"reader": reader})
        if form.injection_attempt:
            store.append(case_id, "finding", {"kind": "injection_attempt"})
    elif stage == "evidence":
        form = Form.model_validate(store.last(case_id, "form"))
        store.append(case_id, "evidence", gather(form).model_dump(mode="json"))
    else:
        _redecide(case_id)
    return stage


def choose_company(case_id: str, domain: str) -> Decision:
    """Lookalike case: the broker picks a candidate; we re-gather for it."""
    form = Form.model_validate(store.last(case_id, "form")).model_copy(update={"domain": domain})
    store.append(case_id, "form", form.model_dump(mode="json"))
    store.append(case_id, "evidence", gather(form).model_dump(mode="json"))
    return _redecide(case_id)


def answer(case_id: str, field: str, question: str, reply: str, options: Optional[list[str]] = None) -> FieldReading:
    """Read a free-text reply into one field. Needs confirm() before it counts."""
    store.append(case_id, "answer_raw", {"field": field, "question": question, "reply": reply})
    reading = read_answer(field, question, reply, options)
    store.append(case_id, "answer_read", reading.model_dump(mode="json"))
    if reading.kind == "refused":
        store.append(case_id, "finding", {"kind": "injection_attempt", "field": field})
    return reading


def confirm(case_id: str, field: str, accept: bool = True) -> Decision:
    st = _state(case_id)
    p = st["pending"].get(field)
    if p is None:
        raise KeyError(f"no pending answer for {field}")
    if not accept:
        store.append(case_id, "answer_rejected", {"field": field})
        return Decision.model_validate(store.last(case_id, "decision"))
    reading = FieldReading.model_validate(p)
    if field == "company" and reading.kind == "value":
        domain = _company_domain(case_id, str(reading.value))
        if domain:  # same as picking the candidate in the Company box: re-gather for it
            store.append(case_id, "answer_confirmed_company", {"value": reading.value, "domain": domain})
            return choose_company(case_id, domain)
    fact = followup_fact(reading, store.now_iso())
    if fact is None:  # a refused reading (e.g. an injection attempt) records nothing
        store.append(case_id, "answer_rejected", {"field": field})
        return Decision.model_validate(store.last(case_id, "decision"))
    n = 1 + sum(1 for f in st["answers"] if f.field == field)
    if n > 1:  # second answer to the same field (e.g. band after "don't know"): distinct id
        fact = fact.model_copy(update={"id": f"followup_{field}_{n}"})
    store.append(case_id, "answer_confirmed", {"fact": fact.model_dump(mode="json")})
    return _redecide(case_id)


_DOMAIN = re.compile(r"^(?:https?://)?(?:www\.)?([a-z0-9-]+(?:\.[a-z0-9-]+)+)/?$", re.I)


def _company_domain(case_id: str, value: str) -> Optional[str]:
    """A confirmed company answer -> the domain to re-gather for, or None.
    Matches one of the decision's candidates by its option label, name or domain;
    otherwise a reply that is itself a website (the 'could not find' question)."""
    d = store.last(case_id, "decision") or {}
    v = value.strip().lower()
    for c in d.get("candidates") or []:
        label = f"{c.get('name')} ({c.get('location') or c.get('domain') or c.get('company_id')})"
        if c.get("domain") and v in {label.lower(), str(c.get("name", "")).lower(), c["domain"].lower()}:
            return c["domain"]
    m = _DOMAIN.match(value.strip())
    return m.group(1).lower() if m else None


def skip(case_id: str, field: str, question: str = "") -> Decision:
    reading = FieldReading(field=field, kind="unknown", display="Skipped: I'll apply the loading for this unknown.")
    store.append(case_id, "answer_read", reading.model_dump(mode="json"))
    return confirm(case_id, field, True)


def what_if(case_id: str, fact_id: str, value=None, status: str = "matches",
            also: Optional[list[str]] = None) -> Decision:
    """'What would change my mind': re-decide with one fact changed (plus any facts a flip says
    must be cleared with it). Not persisted."""
    st = _state(case_id)
    cleared = set(also or [])
    facts = []
    for f in _all_facts(st):
        if f.id == fact_id:
            upd = {"status": status}
            if value is not None:
                upd["value"] = value
            f = Fact.model_validate({**f.model_dump(), **upd})
        elif f.id in cleared:
            f = Fact.model_validate({**f.model_dump(), "status": status})
        facts.append(f)
    return _decide(case_id, st, facts)


def view(case_id: str) -> dict:
    """Everything the screen needs for one case."""
    st = _state(case_id)
    d = store.last(case_id, "decision")
    ev = st["evidence"]
    raw = _all_facts(st) if (st["form"] and ev) else []
    facts = raw + derive(raw)  # estimates shown with their working (Decide re-derives the same ones)
    out = {
        "case_id": case_id,
        "prompt": store.events(case_id)[0]["payload"]["text"],
        "form": st["form"].model_dump(mode="json") if st["form"] else None,
        "resolution": ev.resolution.model_dump(mode="json") if ev else None,
        "facts": [f.model_dump(mode="json") for f in facts],
        "calls": [c.model_dump(mode="json") for c in ev.calls] if ev else [],
        "news_checked": [n.model_dump(mode="json") for n in ev.news_checked] if ev else [],
        "decision": d,
        "pending": list(st["pending"].values()),
        "reader": (store.last(case_id, "reader") or {}).get("reader"),
        "duplicate_of": _duplicate_of(case_id, d),
        "events": [{"seq": e["seq"], "kind": e["kind"], "at": e["at"]} for e in store.events(case_id)],
        "next_stage": next_stage(case_id),
        # line by line, base to premium; None unless priced (and it must reconcile with the decision)
        "breakdown": breakdown(raw) if d and d.get("premium_inr") is not None else None,
    }
    out["risk_map"] = insights.build(out) if d else []
    return out


def risk_map_words(case_id: str) -> dict:
    """Headline + summary per circle. An LLM may write them (cached); colours never come from it."""
    v = view(case_id)
    words, who = insights.narrate(v["risk_map"], (v["decision"] or {}).get("outcome"))
    return {"words": words, "writer": who}


def _duplicate_of(case_id: str, d: Optional[dict]) -> Optional[str]:
    """Same request sent twice: an earlier case with the same decision hash is the record."""
    if not d:
        return None
    for c in reversed(store.list_cases(200)):
        if c["case_id"] == case_id:
            return None
        other = store.last(c["case_id"], "decision")
        if other and other.get("hash") == d.get("hash") and other.get("outcome") != "hold":
            return c["case_id"]
    return None
