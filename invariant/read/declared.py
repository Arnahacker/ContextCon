"""Form -> declared Facts. Quotes are canonical ("headcount: 120"), never the raw prompt."""
from __future__ import annotations

from invariant.shapes import Fact, Form, Source

# fact field -> Form attribute
DECLARED_FIELDS = [
    ("company", "company_name"),
    ("occupancy", "industry"),
    ("headcount", "declared_headcount"),
    ("sites", "declared_sites"),
    ("cover_type", "cover_type"),
    ("sum_insured", "sum_insured_inr"),
    ("export_countries", "countries"),
]


def canonical_quote(field: str, value) -> str:
    if isinstance(value, dict) and set(value) == {"low", "high"}:
        return f"{field}: {value['low']}-{value['high']}"
    if isinstance(value, (list, tuple)):
        return f"{field}: {', '.join(str(v) for v in value)}"
    return f"{field}: {value}"


def declared_facts(form: Form, fetched: str) -> list[Fact]:
    facts = []
    for field, attr in DECLARED_FIELDS:
        value = getattr(form, attr)
        if value is None or value == []:
            continue
        facts.append(Fact(
            id=f"declared_{field}", field=field, value=value, origin="declared",
            evidence_kind="claim", status="consistent_unconfirmed",
            source=Source(what="applicant prompt", fetched=fetched, quote=canonical_quote(field, value)),
        ))
    return facts
