"""Intake gate: Tier 1 fields must be resolved before we price. Pure."""
from __future__ import annotations

from invariant.contracts import TIER1
from invariant.shapes import Fact

from .values import answered, facts_for


def resolved(facts: list[Fact], field: str) -> bool:
    """Any fact (including derived) gives a value that is not cannot_verify."""
    return any(answered(f) for f in facts_for(facts, field))


def missing(facts: list[Fact], required: list[str] | None = None) -> list[str]:
    return [f for f in (required or TIER1) if not resolved(facts, f)]
