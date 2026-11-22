import pytest
from pydantic import ValidationError

from invariant.decide.hashing import decision_hash
from invariant.shapes import Fact, Form, Source


def src(fetched="2026-11-22T12:00:00+05:30"):
    return Source(what="POST /company/enrich -> headcount.total", fetched=fetched, quote="headcount.total: 310")


def test_fact_without_source_is_impossible():
    with pytest.raises(ValidationError):
        Fact(id="h", field="headcount", value=310, origin="crustdata", evidence_kind="lower_bound",
             status="contradicts", company_match="company_id")


def test_cannot_verify_needs_no_source():
    Fact(id="c", field="claims_history", origin="declared", evidence_kind="claim", status="cannot_verify")


def test_evidence_fact_must_state_company_match():
    with pytest.raises(ValidationError):
        Fact(id="h", field="headcount", value=310, origin="crustdata", evidence_kind="lower_bound",
             status="contradicts", source=src())


def test_hash_ignores_fetch_time_and_order():
    a = Fact(id="a", field="headcount", value=310, origin="crustdata", evidence_kind="lower_bound",
             status="contradicts", company_match="company_id", source=src())
    b = Fact(id="b", field="sites", value=4, origin="crustdata", evidence_kind="direct",
             status="contradicts", company_match="company_id", source=src())
    a2 = a.model_copy(update={"source": src("2026-11-22T13:00:00+05:30")})
    assert decision_hash("1", [a, b], "v1") == decision_hash("1", [b, a2], "v1")
    assert decision_hash("1", [a, b], "v1") != decision_hash("1", [a, b], "v2")


def test_form_is_frozen():
    f = Form(company_name="X")
    with pytest.raises(ValidationError):
        f.company_name = "Y"
