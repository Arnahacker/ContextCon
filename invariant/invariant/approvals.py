"""Nothing irreversible leaves without a person. One queue, one decorator.

If you are about to write code that sends, pays, binds or rejects anywhere
else in this repo: don't. Route it through here.
"""
from __future__ import annotations
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Callable

IRREVERSIBLE = {"send_quote", "decline_applicant", "bind_policy",
                "send_endorsement", "email_broker"}


@dataclass
class Pending:
    id: str
    action: str
    summary: str
    payload: dict[str, Any]
    state: str = "waiting"      # waiting | approved | rejected
    result: Any = None

    def to_dict(self): return asdict(self)


class ApprovalQueue:
    def __init__(self):
        self.items: dict[str, Pending] = {}

    def request(self, action: str, summary: str, payload: dict) -> Pending:
        if action not in IRREVERSIBLE:
            raise ValueError(f"{action} is not on the irreversible list; add it there first")
        p = Pending(id=uuid.uuid4().hex[:8], action=action, summary=summary, payload=payload)
        self.items[p.id] = p
        return p

    def approve(self, pid: str, run_once: Callable[[Pending], Any] | None = None):
        p = self.items[pid]
        if p.state == "approved":
            return p                      # idempotent: approving twice sends once
        p.state = "approved"
        if run_once is not None:
            p.result = run_once(p)
        return p

    def reject(self, pid: str):
        p = self.items[pid]
        p.state = "rejected"
        return p

    def waiting(self) -> list[Pending]:
        return [p for p in self.items.values() if p.state == "waiting"]
