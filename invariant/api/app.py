"""HTTP API + the one-page UI."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")  # keys, before any layer reads them

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from invariant.case import service, store, testrun

STATIC = Path(__file__).parent / "static"
app = FastAPI(title="INVARIANT")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


class NewCase(BaseModel):
    prompt: str


class Answer(BaseModel):
    field: str
    question: str = ""
    reply: str
    options: Optional[list[str]] = None


class Confirm(BaseModel):
    field: str
    accept: bool = True


class Choose(BaseModel):
    domain: str


class WhatIf(BaseModel):
    fact_id: str
    value: Any = None
    status: str = "matches"
    also: list[str] = []  # facts a combined flip clears together with fact_id


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.post("/api/cases")
def create(body: NewCase):
    if not body.prompt.strip():
        raise HTTPException(400, "empty prompt")
    try:
        return service.view(service.run_case(body.prompt))
    except LookupError as exc:  # no LLM key / fixture and no fallback could read it
        raise HTTPException(422, f"Could not read this prompt: {exc}") from exc


@app.get("/api/cases")
def cases():
    return store.list_cases()


@app.get("/api/cases/{case_id}")
def get_case(case_id: str):
    return service.view(case_id)


@app.post("/api/cases/{case_id}/resume")
def resume(case_id: str):
    service.resume(case_id)
    return service.view(case_id)


@app.post("/api/cases/{case_id}/answer")
def answer(case_id: str, body: Answer):
    reading = service.answer(case_id, body.field, body.question, body.reply, body.options)
    return {"reading": reading.model_dump(mode="json"), "case": service.view(case_id)}


@app.post("/api/cases/{case_id}/confirm")
def confirm(case_id: str, body: Confirm):
    service.confirm(case_id, body.field, body.accept)
    return service.view(case_id)


@app.post("/api/cases/{case_id}/skip")
def skip(case_id: str, body: Confirm):
    service.skip(case_id, body.field)
    return service.view(case_id)


@app.post("/api/cases/{case_id}/choose")
def choose(case_id: str, body: Choose):
    service.choose_company(case_id, body.domain)
    return service.view(case_id)


@app.post("/api/cases/{case_id}/whatif")
def what_if(case_id: str, body: WhatIf):
    return service.what_if(case_id, body.fact_id, body.value, body.status, body.also).model_dump(mode="json")


@app.post("/api/invariance")
def invariance():
    return testrun.run_rewrites()


@app.post("/api/tests")
def tests():
    return testrun.run_all()


@app.get("/api/meter")
def meter():
    try:
        from invariant.evidence import client

        return client.meter_snapshot()
    except Exception as exc:  # meter must never break the screen
        return {"error": repr(exc)}
