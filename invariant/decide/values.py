"""Small read-only helpers over a list of Facts. Pure."""
from __future__ import annotations

from typing import Any, Iterable, Optional

from invariant.shapes import Fact

Range = tuple[float, float]

# Which origin wins when several facts give a value for the same field.
ORIGIN_RANK = {"applicant_followup": 0, "declared": 1, "derived": 2, "crustdata": 3, "registry": 4, "web": 5}
EVIDENCE_ORIGINS = ("crustdata", "web", "registry")


def answered(f: Fact) -> bool:
    return f.status != "cannot_verify" and f.value is not None


def facts_for(facts: Iterable[Fact], field: str) -> list[Fact]:
    return sorted((f for f in facts if f.field == field), key=lambda f: f.id)


def pick(facts: Iterable[Fact], field: str) -> Optional[Fact]:
    """Best answered fact for a field: follow-up > declared > derived > evidence."""
    cands = [f for f in facts_for(facts, field) if answered(f)]
    if not cands:
        return None
    return min(cands, key=lambda f: (ORIGIN_RANK[f.origin], f.id))


def num_range(v: Any) -> Optional[Range]:
    """A number -> (v, v); {"low": x, "high": y} -> (x, y). Anything else -> None."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return (float(v), float(v))
    if isinstance(v, dict) and isinstance(v.get("low"), (int, float)):
        lo = float(v["low"])
        hi = v.get("high")
        return (lo, float(hi) if isinstance(hi, (int, float)) else lo)
    return None


def is_range(v: Any) -> bool:
    r = num_range(v)
    return r is not None and r[0] != r[1]


def mid(r: Range) -> float:
    return (r[0] + r[1]) / 2


def fact_range(f: Optional[Fact]) -> Optional[Range]:
    """A fact's (low, high): its derivation range when derived, else its value."""
    if f is None:
        return None
    if f.derivation:
        return f.derivation.range
    return num_range(f.value)


def as_bool(v: Any) -> Optional[bool]:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("yes", "true", "owned", "own", "y"):
            return True
        if s in ("no", "false", "rented", "rent", "leased", "n"):
            return False
    return None


def headcount(facts: Iterable[Fact]) -> Optional[float]:
    """Largest headcount any source gives (a record is a lower bound, so max is safe)."""
    vals = [mid(r) for f in facts_for(facts, "headcount") if answered(f) and (r := num_range(f.value))]
    return max(vals) if vals else None


def declared_headcount(facts: Iterable[Fact]) -> Optional[float]:
    vals = [mid(r) for f in facts_for(facts, "headcount")
            if answered(f) and f.origin in ("declared", "applicant_followup") and (r := num_range(f.value))]
    return max(vals) if vals else None


def occupancy(facts: Iterable[Fact]) -> Optional[str]:
    f = pick(facts, "occupancy")
    return f.value if f and isinstance(f.value, str) else None


def latest_fetched(facts: Iterable[Fact]) -> str:
    stamps = [f.source.fetched for f in facts if f.source]
    return max(stamps) if stamps else ""


def crore(x: float) -> str:
    """Readable rupees: 506166697670 -> 'Rs 50,617 Cr', 4500000 -> 'Rs 45 lakh'."""
    if abs(x) >= 1e7:
        return f"{inr(round(x / 1e7))} Cr"
    if abs(x) >= 1e5:
        return f"{inr(round(x / 1e5))} lakh"
    return inr(x)


def inr(x: float) -> str:
    """Indian digit grouping: 20125000 -> 'Rs 2,01,25,000'."""
    n = int(round(x))
    s = str(abs(n))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        s = ",".join(groups + [tail])
    return ("-" if n < 0 else "") + "Rs " + s
