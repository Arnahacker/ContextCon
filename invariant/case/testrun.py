"""Runs the ten cases (answers written before code) and the eight hero rewrites."""
from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path

from invariant.case import service

ROOT = Path(__file__).resolve().parents[2]
CASES = json.loads((ROOT / "tests/cases/cases.json").read_text(encoding="utf-8"))["cases"]
REWRITES_FILE = ROOT / "tests/rewrites/hero_rewrites.json"


@contextmanager
def _fault(fault: dict | None):
    if not fault:
        yield
        return
    old = os.environ.get("INVARIANT_FAULT")
    os.environ["INVARIANT_FAULT"] = ",".join(f"{k}:{v}" for k, v in fault.items())
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("INVARIANT_FAULT", None)
        else:
            os.environ["INVARIANT_FAULT"] = old


def _run(case: dict) -> tuple[str, dict]:
    with _fault(case.get("fault")):
        cid = service.run_case(case["prompt"])
        exp = case["expected"]
        # cases with answers written down: answer them, as a broker would
        answers = exp.get("answers")
        if not answers and case.get("same_as_case"):  # a reworded copy gets the same answers
            ref = next(c for c in CASES if c["id"] == case["same_as_case"])
            answers = ref["expected"].get("answers")
        if answers:
            for field, value in answers.items():
                service.answer(cid, field, f"({field})", str(value))
                service.confirm(cid, field, True)
    return cid, service.view(cid)


def run_all() -> list[dict]:
    results, hashes = [], {}
    for case in CASES:
        try:
            cid, v = _run(case)
            d = v["decision"] or {}
            hashes[case["id"]] = d.get("hash")
            exp = case["expected"]
            exp_final = exp.get("after_answers", exp)
            checks = []
            if "outcome" in exp_final:
                checks.append(("outcome", exp_final["outcome"], d.get("outcome")))
            if "hold_reason" in exp_final:
                checks.append(("hold_reason", exp_final["hold_reason"], d.get("hold_reason")))
            for rule in exp_final.get("rules", []):
                got = [s["rule"] for s in d.get("steps", [])]
                checks.append((f"rule {rule}", True, rule in got))
            if "candidates" in exp_final:
                checks.append(("candidates", exp_final["candidates"], len(d.get("candidates", []))))
            for qf in exp_final.get("question_fields", []):
                checks.append((f"question {qf}", True, qf in [q["field"] for q in d.get("questions", [])]))
            if "finding" in exp_final:
                checks.append(("finding", True, any(exp_final["finding"] in f for f in d.get("findings", []))))
            same = exp.get("same_hash_as_case")
            if same:
                checks.append((f"same hash as case {same}", hashes.get(same), d.get("hash")))
            ok = all(e == g for _, e, g in checks)
            results.append({"id": case["id"], "name": case["name"], "case_id": cid, "ok": ok,
                            "outcome": d.get("outcome"), "hash": d.get("hash"),
                            "checks": [{"what": w, "expected": e, "got": g, "ok": e == g} for w, e, g in checks]})
        except Exception as exc:  # a crash is a failed case, shown on screen
            results.append({"id": case["id"], "name": case["name"], "ok": False, "error": repr(exc)})
    return results


def run_rewrites() -> list[dict]:
    rewrites = json.loads(REWRITES_FILE.read_text(encoding="utf-8"))
    items = rewrites if isinstance(rewrites, list) else rewrites.get("rewrites", [])
    out = []
    for r in items:
        text = (r.get("prompt") or r.get("text")) if isinstance(r, dict) else r
        style = r.get("style", "") if isinstance(r, dict) else ""
        cid = service.run_case(text)
        v = service.view(cid)
        out.append({"style": style, "text": text, "case_id": cid, "form": v["form"],
                    "outcome": (v["decision"] or {}).get("outcome"), "hash": (v["decision"] or {}).get("hash")})
    return out
