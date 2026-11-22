"""Every call, what it cost, whether it was cached. The cost meter reads this."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Callable, Optional


@dataclass
class Entry:
    name: str
    credits: float = 0.0
    cached: bool = False
    ms: int = 0
    ok: bool = True
    note: str = ""

    def to_dict(self): return asdict(self)


@dataclass
class Ledger:
    entries: list[Entry] = field(default_factory=list)
    # called with each Entry as it is recorded, so the screen can show calls
    # live. Observes only: it can never change what was recorded.
    listener: Optional[Callable[[Entry], None]] = field(default=None, repr=False,
                                                         compare=False)

    def add(self, name, credits=0.0, cached=False, ms=0, ok=True, note=""):
        e = Entry(name, credits, cached, ms, ok, note)
        self.entries.append(e)
        if self.listener:
            try:
                self.listener(e)
            except Exception:
                pass

    @property
    def credits(self) -> float:
        return round(sum(e.credits for e in self.entries if not e.cached), 2)

    @property
    def live_calls(self) -> int:
        return sum(1 for e in self.entries if not e.cached and e.ok)

    @property
    def cached_calls(self) -> int:
        return sum(1 for e in self.entries if e.cached)

    def to_dict(self):
        return {"entries": [e.to_dict() for e in self.entries],
                "credits": self.credits, "live_calls": self.live_calls,
                "cached_calls": self.cached_calls,
                "rupees": round(self.credits * 0.5, 2)}
