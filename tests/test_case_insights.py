"""The risk map and the step-by-step run. Colours come from rules and records only."""
from invariant.case import insights, service

HERO = ("A leather exporter, Kanpur Hide Exports Pvt Ltd, applying for cover says it has 120 "
        "employees across three units. Check that against public data and tell me what does not match.")


def _map(v):
    return {n["id"]: n for n in v["risk_map"]}


def test_step_runs_one_stage_at_a_time_then_stops():
    cid = service.store.new_case(HERO)
    assert [service.step(cid) for _ in range(4)] == ["read", "evidence", "decide", None]
    assert service.view(cid)["next_stage"] is None


def test_hero_findings_are_red_and_cover_is_waiting():
    m = _map(service.view(service.run_case(HERO)))
    assert m["identity"]["status"] == "good"
    assert {m[k]["status"] for k in ("staff", "sites", "work")} == {"bad"}
    assert m["cover"]["status"] == "warn" and m["cover"]["open_questions"]
    assert "sanctions" not in m  # no sanctions check ran: no circle for it


def test_lookalike_never_paints_unchecked_areas_green():
    v = service.view(service.run_case("Shree Balaji Exports, about 60 people, fire cover 2 crore."))
    m = _map(v)
    assert m["identity"]["status"] == "bad"
    # only the applicant's word: grey, not green
    assert m["staff"]["status"] == "neutral"
    assert any("applicant's word" in p for p in m["staff"]["points"])


def test_decline_turns_news_red():
    m = _map(service.view(service.run_case(
        "Vellore Tanners Ltd, Ranipet, 150 employees, 2 units, need fire cover for 10 crore.")))
    assert m["news"]["status"] == "bad" and m["news"]["issues"][0]["rule"] == "CONFIRMED_FIRE"


def test_refer_view_carries_a_reconciled_breakdown():
    cid = service.run_case(HERO)
    for field, reply in (("cover_type", "fire"), ("sum_insured", "5 crore")):
        q = service.view(cid)["decision"]["questions"][0]
        assert q["field"] == field
        service.answer(cid, field, q["ask"], reply, q["options"] or None)
        service.confirm(cid, field, True)
    v = service.view(cid)
    assert v["decision"]["outcome"] == "refer"
    assert v["breakdown"]["total"] == v["decision"]["premium_inr"]


def test_ai_wording_cannot_bring_in_numbers_or_change_colours(monkeypatch):
    nodes = insights.build(service.view(service.run_case(HERO)))
    from invariant.read import llm

    def fake(**kw):
        return {"areas": [
            {"id": "staff", "headline": "Staff understated", "summary": "Records show 310 staff, said 120."},
            {"id": "sites", "headline": "Sites fine", "summary": "They have 9 more sites."},  # 9 is invented
        ]}
    monkeypatch.setattr(llm, "call_tool", fake)
    words, who = insights.narrate(nodes, "refer")
    assert words["staff"]["summary"].startswith("Records show 310")      # numbers from the points: kept
    assert words["sites"] == insights.fallback(next(n for n in nodes if n["id"] == "sites"))  # invented: dropped
    assert {n["id"]: n["status"] for n in nodes} == {n["id"]: n["status"] for n in insights.build(
        service.view(service.run_case(HERO)))}                           # wording never touches colour


def test_no_llm_means_rule_wording():
    nodes = insights.build(service.view(service.run_case(HERO)))
    words, who = insights.narrate(nodes, "hold")
    assert who == "rules" and set(words) == {n["id"] for n in nodes}


def test_summary_lists_each_case_with_its_outcome():
    cid = service.run_case("Vellore Tanners Ltd, Ranipet, 150 employees, 2 units, need fire cover for 10 crore.")
    row = next(r for r in service.summary() if r["case_id"] == cid)
    assert row["outcome"] == "decline" and row["company"] == "Vellore Tanners Ltd"
    assert row["premium_inr"] is None and row["cover_type"] == "fire"
