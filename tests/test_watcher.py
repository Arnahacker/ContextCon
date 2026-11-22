"""Company watcher (demo companies, offline) and case deletion."""
import pytest

from invariant.case import store, watcher
from invariant.evidence import watch


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "cases.sqlite")


def test_only_demo_companies_are_watchable():
    names = {c["name"] for c in watch.watchable()}
    assert "Agra Footwear Works" in names and "Tiruppur Stitchline Garments" in names
    assert "Super Tannery Limited" not in names  # a real company: never on the demo watcher
    with pytest.raises(watch.WatchUnavailable):
        watcher.start("4889")


def test_watcher_refuses_outside_offline_mode(monkeypatch):
    monkeypatch.delenv("INVARIANT_OFFLINE", raising=False)
    monkeypatch.delenv("INVARIANT_EVIDENCE_OFFLINE", raising=False)
    assert watch.watchable() == []
    with pytest.raises(watch.WatchUnavailable):
        watcher.start("700102")


def test_agra_checks_follow_the_script_and_every_change_is_sourced():
    w = watcher.start("700102")
    assert w["baseline"]["headcount"] == 80 and w["checks"] == []
    first = watcher.check_now("700102")["checks"][-1]
    assert first["changes"] == []  # the first check finds nothing
    second = watcher.check_now("700102")["checks"][-1]
    fields = {c["field"]: c for c in second["changes"]}
    assert fields["headcount"]["before"] == 80 and fields["headcount"]["after"] == 118
    assert "Firozabad" in fields["sites"]["after"]
    for c in second["changes"]:
        src = c["fact"]["source"]
        assert src["what"].startswith("POST /company/enrich") and src["quote"]
    assert watcher.check_now("700102")["checks"][-1]["changes"] == []  # past the script: no change


def test_tiruppur_new_job_ad_has_no_invented_date():
    ch = watcher.check_now(watcher.start("700103")["company_id"])["checks"][-1]["changes"][0]
    assert ch["after"]["job_title"] == "Screen Printing Operator (Solvent Inks)"
    assert ch["fact"]["source"]["dated"] is None  # job search gives no date


def test_watching_twice_keeps_one_watch_and_stop_removes_it():
    a = watcher.start("700101")
    watcher.check_now("700101")
    b = watcher.start("700101")
    assert a["started"] == b["started"] and len(b["checks"]) == 1
    watched = [c for c in watcher.overview()["companies"] if c["watch"]]
    assert [c["company_id"] for c in watched] == ["700101"]
    watcher.stop("700101")
    assert not any(c["watch"] for c in watcher.overview()["companies"])
    with pytest.raises(KeyError):
        watcher.check_now("700101")


def test_delete_one_case_and_all_cases():
    a, b = store.new_case("first"), store.new_case("second")
    store.append(a, "note", {"x": 1})
    assert store.delete_case(a) is True
    assert store.events(a) == [] and [c["case_id"] for c in store.list_cases()] == [b]
    assert store.delete_case(a) is False
    assert store.delete_all_cases() == 1 and store.list_cases() == []
