"""Answering the 'which company' question in the broker chat resolves the case,
exactly like the candidate buttons in the Company box."""
from invariant.case import service


def test_company_option_answer_resolves_lookalike():
    cid = service.run_case("Shree Balaji Exports, about 60 people, fire cover 2 crore.")
    d = service.view(cid)["decision"]
    assert d["hold_reason"] == "ambiguous_company"
    q = next(q for q in d["questions"] if q["field"] == "company")
    pick = next(o for o in q["options"] if "Surat" in o)
    service.answer(cid, "company", q["ask"], pick, q["options"])
    service.confirm(cid, "company", True)
    v = service.view(cid)
    assert v["resolution"]["status"] == "resolved"
    assert v["resolution"]["domain"] == "balajisurat.example"
    assert v["decision"]["hold_reason"] != "ambiguous_company"
    assert not v["pending"]
