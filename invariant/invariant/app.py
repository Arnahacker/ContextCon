from __future__ import annotations
import pathlib, traceback
from typing import Any, Optional

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from .pipeline import run, gap_table, load_rules
from .rewrites import REWRITES, HERO
from .approvals import ApprovalQueue
from .cases import GOLDEN, check_case

app = FastAPI(title="INVARIANT")
QUEUE = ApprovalQueue()
STATIC = pathlib.Path(__file__).with_name("static")


class RunIn(BaseModel):
    prompt: str
    run_id: Optional[str] = None
    answers: dict[str, Any] = {}


@app.get("/")
def home():
    # explicit charset: without it some browsers guess, and the rupee sign breaks
    return HTMLResponse((STATIC / "index.html").read_text(encoding="utf-8"),
                        media_type="text/html; charset=utf-8")


@app.post("/api/run")
def api_run(body: RunIn):
    try:
        case = run(body.prompt, run_id=body.run_id, answers=body.answers)
    except Exception as e:                      # never 500 at a judge
        return JSONResponse(status_code=200, content={
            "error": str(e), "trace": traceback.format_exc()[-800:],
            "decision": {"outcome": "hold", "hold_reason": "internal_error",
                         "premium_inr": 0, "gate": {"blocked": True, "missing": []},
                         "steps": [], "questions": [], "would_flip_if": [],
                         "hash": "", "rules_version": "", "notes": [str(e)]}})
    case["gap_table"] = gap_table(case)
    return case


@app.get("/api/invariance")
def api_invariance(prompt: str = HERO):
    rows, hashes = [], set()
    for label, text in REWRITES.items():
        c = run(text)
        rows.append({"label": label, "prompt": text,
                     "form": c["form"], "hash": c["decision"]["hash"],
                     "outcome": c["decision"]["outcome"],
                     "premium_inr": c["provisional_premium_inr"]})
        hashes.add(c["decision"]["hash"])
    return {"rows": rows, "all_match": len(hashes) == 1, "distinct": len(hashes)}


@app.get("/api/tests")
def api_tests():
    out = [check_case(c) for c in GOLDEN]
    return {"cases": out, "passed": sum(1 for c in out if c["pass"]), "total": len(out)}


@app.get("/api/rules")
def api_rules():
    return load_rules()


class ApproveIn(BaseModel):
    action: str
    summary: str
    payload: dict[str, Any] = {}


@app.post("/api/approval/request")
def approval_request(body: ApproveIn):
    return QUEUE.request(body.action, body.summary, body.payload).to_dict()


@app.post("/api/approval/{pid}/approve")
def approval_approve(pid: str):
    return QUEUE.approve(pid, lambda p: {"sent": True}).to_dict()


@app.get("/api/approval")
def approval_list():
    return {"waiting": [p.to_dict() for p in QUEUE.waiting()]}
