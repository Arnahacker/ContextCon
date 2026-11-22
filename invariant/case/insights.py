"""The risk map: one circle per area we checked, coloured by CODE from the decision.

Status (the colour) comes only from the decision's own rules and the sourced facts:
  bad      a rule that refers or declines fired in this area
  warn     a loading, a gap we could not verify, or a question still open
  good     records were checked and nothing is wrong
  neutral  nothing was checked here (e.g. no sanctions key)
An LLM may only write the short heading and summary for each circle (narrate()); it
never sets a colour, a fact or a number. Numbers it writes must already be in the
points it was given, or its text is dropped for ours.
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional

from invariant.decide.rules import DECLINE_RULES, REFER_RULES

AREAS: list[dict[str, Any]] = [
    {"id": "identity", "label": "Company", "fields": ["company", "year_founded"], "rules": []},
    {"id": "staff", "label": "Staff", "fields": ["headcount", "headcount_trend", "confirm_headcount", "wages", "pf_monthly"],
     "rules": ["HEADCOUNT_UNDERSTATED"]},
    {"id": "sites", "label": "Locations", "fields": ["sites", "confirm_sites"], "rules": ["UNDECLARED_SITE"]},
    {"id": "work", "label": "Nature of work", "fields": ["occupancy", "hazardous_activity", "confirm_hazard"],
     "rules": ["UNDECLARED_HAZARD", "DISCLOSED_HAZARD", "OCCUPANCY_MISMATCH"]},
    {"id": "news", "label": "News", "fields": ["adverse_event"], "rules": ["ADVERSE_EVENT", "CONFIRMED_FIRE"]},
    {"id": "sanctions", "label": "Sanctions", "fields": ["sanctions"], "rules": ["SANCTIONS_MATCH"]},
    {"id": "claims", "label": "Past claims", "fields": ["claims_history"], "rules": ["CLAIMS_HISTORY_UNKNOWN"]},
    {"id": "cover", "label": "Cover & values",
     "fields": ["cover_type", "sum_insured", "building_owned", "building_area_sqft", "roof_type", "monthly_sales",
                "stock_weeks", "machinery_value", "building_value", "stock_value", "cargo_value", "marine_route",
                "liability_limit", "turnover", "export_countries"],
     "rules": ["DERIVED_VALUE", "UNDISCLOSED_ESSENTIAL", "COVER_NOT_PRICED", "UNKNOWN_"]},
]

LABEL = {"headcount": "staff", "headcount_trend": "staff trend", "year_founded": "founded", "sites": "sites",
         "occupancy": "line of business", "hazardous_activity": "hazardous work", "adverse_event": "news",
         "sanctions": "sanctions", "claims_history": "past claims", "cover_type": "cover",
         "sum_insured": "sum insured", "turnover": "yearly revenue", "cargo_value": "cargo value",
         "liability_limit": "limit of cover", "wages": "yearly wages", "confirm_sites": "applicant on extra sites",
         "confirm_hazard": "applicant on hazardous work", "confirm_headcount": "applicant on staff figure"}
COVER = {"fire": "fire", "wc": "workmen's comp", "fire_wc": "fire + workmen's comp", "marine": "marine cargo",
         "liability": "liability"}


def _money(v: float) -> str:
    if v >= 1e7:
        return f"₹{v / 1e7:.1f} Cr".replace(".0 Cr", " Cr")
    if v >= 1e5:
        return f"₹{v / 1e5:.1f} lakh".replace(".0 lakh", " lakh")
    return f"₹{int(v):,}"


def _fmt(field: str, v: Any) -> str:
    if v is None:
        return "unknown"
    if isinstance(v, dict):
        if "low" in v and "high" in v:
            return f"{_fmt(field, v['low'])} to {_fmt(field, v['high'])}"
        return str(v.get("title") or v.get("activity") or v.get("city") or v.get("name") or v.get("caption") or "")
    if field == "cover_type":
        return COVER.get(str(v), str(v))
    if field == "headcount_trend" and isinstance(v, (int, float)):
        return f"{v:+.0f}% in a year"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, (int, float)) and field in ("sum_insured", "turnover", "cargo_value", "liability_limit",
                                                 "machinery_value", "building_value", "stock_value", "wages",
                                                 "monthly_sales", "pf_monthly"):
        return _money(v)
    return str(v)


def _said(f: dict) -> bool:
    return f["origin"] in ("declared", "applicant_followup")


def _points(area: dict, facts: list[dict]) -> list[str]:
    out = []
    for field in area["fields"]:
        fs = [f for f in facts if f["field"] == field]
        if not fs:
            continue
        name = LABEL.get(field, field.replace("_", " "))
        said = [_fmt(field, f["value"]) for f in fs if _said(f) and f["status"] != "cannot_verify"]
        dont_know = any(_said(f) and f["status"] == "cannot_verify" for f in fs)
        rec = [f for f in fs if not _said(f) and f["origin"] != "derived"]
        est = [f for f in fs if f["origin"] == "derived"]
        if field in ("sites", "hazardous_activity", "adverse_event") and rec:
            listed = [_fmt(field, f["value"]) for f in rec if isinstance(f["value"], dict)]
            counts = [_fmt(field, f["value"]) for f in rec if not isinstance(f["value"], dict)]
            if counts:
                out.append(f"Records show {counts[0]} {name}" + (f"; applicant said {said[0]}" if said else ""))
            if listed:
                what = {"sites": "Also on record at", "hazardous_activity": "Job ads show",
                        "adverse_event": "News found"}[field]
                out.append(f"{what}: {', '.join(dict.fromkeys(listed))}")
            continue
        parts = []
        if said:
            parts.append(f"applicant said {said[-1]}")
        if dont_know:
            parts.append("applicant did not know")
        if rec:
            r = rec[0]
            word = {"contradicts": "records show", "matches": "records confirm",
                    "undeclared": "records show", "consistent_unconfirmed": "records show"}.get(r["status"], "records show")
            parts.append(f"{word} {_fmt(field, r['value'])}")
        if est and not said and not rec:
            parts.append(f"estimated at {_fmt(field, est[0]['value'])}")
        if parts:
            out.append(f"{name.capitalize()}: {'; '.join(parts)}")
    return out


def _rules_in(area: dict, steps: list[dict]) -> list[dict]:
    return [s for s in steps if any(s["rule"] == r or (r.endswith("_") and s["rule"].startswith(r)) for r in area["rules"])]


def build(view: dict) -> list[dict]:
    """The circles, from a case view (service.view)."""
    d = view.get("decision") or {}
    facts = view.get("facts") or []
    steps = d.get("steps") or []
    res = view.get("resolution") or {}
    open_qs = {q["field"] for q in d.get("questions") or []}
    findings = d.get("findings") or []
    nodes = []
    for area in AREAS:
        fs = [f for f in facts if f["field"] in area["fields"]]
        if area["id"] == "sanctions" and not fs:
            continue  # only shown when a sanctions check actually ran (a match still shows, red)
        rs = _rules_in(area, steps)
        points = _points(area, facts)
        # green means a RECORD backs it. The applicant's own word is not a check -- except for
        # cover and past claims, where no public record exists and their answer is the check.
        on_record = [f for f in fs if not _said(f)]
        if on_record or (fs and area["id"] in ("cover", "claims")):
            status = "good"
            if not on_record and area["id"] in ("cover", "claims"):
                points.append("No public record exists for this: the applicant's answer is what we use")
        else:
            status = "neutral"
            if fs:
                points.append("Only the applicant's word so far: not checked against a record")
        issues = []
        if any(s["rule"] in DECLINE_RULES or s["rule"] in REFER_RULES for s in rs):
            status = "bad"
        elif any(s["multiplier"] > 1 for s in rs):
            status = "warn"
        if status != "bad":
            if any(f["status"] in ("contradicts", "undeclared") and not _said(f) for f in fs):
                status = "warn"
            if open_qs & set(area["fields"]) or (area["id"] == "cover" and "sum_insured" in (d.get("gate") or {}).get("missing", [])):
                status = "warn"  # an open question here: not settled yet
        for s in rs:
            issues.append({"rule": s["rule"], "multiplier": s["multiplier"], "because": s["because"]})
        # area-specific extras
        if area["id"] == "identity":
            st = res.get("status")
            status = {"resolved": "good", "ambiguous": "bad", "not_found": "bad", "unavailable": "warn"}.get(st, "neutral")
            if st == "resolved":
                points = [f"Matched to {res.get('name')} ({res.get('domain') or res.get('company_id')})"] + points
            elif st == "ambiguous":
                points = ["Several companies match this name: we hold rather than guess"] + \
                         [f"Candidate: {c.get('name')} ({c.get('location') or c.get('domain') or ''})" for c in res.get("candidates") or []]
            elif st == "not_found":
                points = ["No company with this name on record"]
        if area["id"] == "news":
            checked = view.get("news_checked") or []
            searched = any("/web/" in (c.get("endpoint") or "") and c.get("ok") for c in view.get("calls") or [])
            if (checked or searched) and status == "neutral":
                status = "good"
            if checked:
                points.append(f"{len(checked)} article(s) read; only ones naming this company count")
            elif searched:
                points.append("Searched the web: nothing names this company")
            elif not fs:
                points.append("No news search ran for this case")
            if any("web" in f for f in findings if f.startswith("evidence_unavailable")):
                status = "warn"
                points.append("The news search did not answer")
        if area["id"] == "staff" and any(f.startswith("shrinking") for f in findings) and status == "good":
            status = "warn"
            points.append("Staff numbers fell sharply over the last year")
        if area["id"] == "cover" and any(f.startswith("underinsurance") for f in findings) and status == "good":
            status = "warn"
            points.append("The amount insured looks too low for the business")
        if area["id"] == "sanctions" and not fs:
            points = ["Not checked: no sanctions-list key configured"]
        for q in sorted(open_qs & set(area["fields"])):
            points.append(f"Waiting for the applicant: {LABEL.get(q, q.replace('_', ' '))}")
        if not points:
            points.append("Nothing was asked or found for this area in this case")
        nodes.append({"id": area["id"], "label": area["label"], "status": status, "points": points,
                      "facts": [f["id"] for f in fs], "issues": issues,
                      "open_questions": sorted(open_qs & set(area["fields"]))})
    return nodes


# ------------------------------------------------------------------ words for the circles

FALLBACK = {"good": "Checks out", "warn": "Needs attention", "bad": "Problem found", "neutral": "Not checked"}


def fallback(node: dict) -> dict:
    head = FALLBACK[node["status"]]
    summary = node["points"][0] if node["points"] else "Nothing on record for this area."
    return {"headline": head, "summary": summary}


_SYSTEM = """You label a risk map for an insurance underwriter. For each area you are given its
status (decided by fixed rules, not by you) and the checked points. Write:
- headline: at most 6 words, plain English, matching the status.
- summary: at most 30 words, using ONLY the points given. Do not add facts, numbers, names,
  opinions or advice that are not in the points. Never change a status.
Return every area id you were given, once."""

_TOOL = {
    "name": "label_risk_map",
    "description": "Short headline and summary for each area of the risk map.",
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["areas"],
        "properties": {"areas": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["id", "headline", "summary"],
            "properties": {"id": {"type": "string"}, "headline": {"type": "string"},
                           "summary": {"type": "string"}}}}},
    },
}

_NUM = re.compile(r"\d[\d,.]*")


def _numbers_ok(text: str, source: str) -> bool:
    src = source.replace(",", "")
    return all(n.replace(",", "").rstrip(".") in src for n in _NUM.findall(text))


def narrate(nodes: list[dict], outcome: Optional[str]) -> tuple[dict[str, dict], str]:
    """{node id: {headline, summary}} and who wrote it ("gemini" / "claude" / "fixture" / "rules")."""
    words = {n["id"]: fallback(n) for n in nodes}
    payload = json.dumps({"decision": outcome, "areas": [{"id": n["id"], "label": n["label"], "status": n["status"],
                                                          "points": n["points"]} for n in nodes]},
                         ensure_ascii=False, sort_keys=True)
    try:
        from invariant.read import llm
        out = llm.call_tool(kind="risk_map", index_key=payload[:200], prompt_version="risk-map-v1",
                            system=_SYSTEM, tool=_TOOL, user_text=payload, save_fixture=False)
        who = llm.last_provider or "llm"
    except Exception:  # no key, offline without a fixture, rate limit: the rule text stands
        return words, "rules"
    by_id = {n["id"]: n for n in nodes}
    used = 0
    for a in out.get("areas") or []:
        n = by_id.get(a.get("id"))
        if not n:
            continue
        head, summ = str(a.get("headline", "")).strip(), str(a.get("summary", "")).strip()
        src = " ".join(n["points"]) + " " + n["label"]
        if not head or not summ or len(head.split()) > 8 or len(summ.split()) > 45:
            continue
        if not (_numbers_ok(head, src) and _numbers_ok(summ, src)):
            continue  # it introduced a number that is not in the facts: keep ours
        words[n["id"]] = {"headline": head, "summary": summ}
        used += 1
    return words, (who if used else "rules")
