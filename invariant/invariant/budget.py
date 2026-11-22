"""A ceiling on every run. Hitting it produces a hold, never a crash."""
from __future__ import annotations
import time
from dataclasses import dataclass


class BudgetExceeded(Exception):
    def __init__(self, what: str, spent, cap):
        super().__init__(f"{what} ceiling hit: {spent} of {cap}")
        self.what, self.spent, self.cap = what, spent, cap


@dataclass
class Budget:
    max_seconds: float = 90.0
    max_credits: float = 400.0
    started: float = 0.0

    def start(self):
        self.started = time.monotonic()
        return self

    @property
    def elapsed(self) -> float:
        return round(time.monotonic() - self.started, 2)

    def check(self, credits_spent: float):
        if self.started and self.elapsed > self.max_seconds:
            raise BudgetExceeded("time", self.elapsed, self.max_seconds)
        if credits_spent > self.max_credits:
            raise BudgetExceeded("credits", credits_spent, self.max_credits)
