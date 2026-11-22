import os, pathlib, tempfile, pytest
import invariant.runlog as runlog
from invariant.ledger import Ledger
from invariant.budget import Budget, BudgetExceeded
from invariant.approvals import ApprovalQueue

def test_once_survives_a_restart(tmp_path, monkeypatch):
    monkeypatch.setattr(runlog, "ROOT", tmp_path)
    monkeypatch.setattr(runlog, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(runlog, "CACHE", tmp_path / "cache")
    calls = []
    log = runlog.RunLog("r1")
    log.once("send:quote:case7", lambda: calls.append(1) or "sent")
    # process dies here. a brand new RunLog object replays the same file:
    log2 = runlog.RunLog("r1")
    log2.once("send:quote:case7", lambda: calls.append(1) or "sent")
    assert len(calls) == 1, "the quote was sent twice after a restart"

def test_cache_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(runlog, "CACHE", tmp_path / "cache")
    k = runlog.request_hash("company/enrich", {"domain": "x.com"})
    assert runlog.cache_get(k) is None
    runlog.cache_put(k, {"employee_count": 310})
    assert runlog.cache_get(k)["employee_count"] == 310
    # same request -> same key, regardless of dict ordering
    assert runlog.request_hash("company/enrich", {"domain": "x.com"}) == k

def test_ledger_counts_only_live_calls():
    l = Ledger()
    l.add("company/identify", credits=5, cached=False)
    l.add("company/enrich", credits=12, cached=True)
    assert l.credits == 5 and l.live_calls == 1 and l.cached_calls == 1

def test_budget_raises_not_crashes():
    b = Budget(max_credits=10).start()
    b.check(5)
    with pytest.raises(BudgetExceeded):
        b.check(99)

def test_approval_is_required_and_idempotent():
    q = ApprovalQueue()
    with pytest.raises(ValueError):
        q.request("tweet_about_it", "nope", {})
    sent = []
    p = q.request("send_quote", "Quote to broker", {"premium": 1})
    assert q.waiting() and p.state == "waiting"
    q.approve(p.id, lambda pending: sent.append(1))
    q.approve(p.id, lambda pending: sent.append(1))
    assert len(sent) == 1, "approving twice sent twice"
