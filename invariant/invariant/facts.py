"""A fact cannot exist without a source. The rule lives in the type, not in code review."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any, Optional
import datetime as _dt

# ---- status: the result of comparing one claim with one piece of evidence
MATCHES = "matches"
CONTRADICTS = "contradicts"
CONSISTENT_UNCONFIRMED = "consistent_unconfirmed"
CANNOT_VERIFY = "cannot_verify"
UNDECLARED = "undeclared"
STATUSES = (MATCHES, CONTRADICTS, CONSISTENT_UNCONFIRMED, CANNOT_VERIFY, UNDECLARED)

# ---- where the value came from
ORIGINS = ("declared", "applicant_followup", "crustdata", "web", "own_site", "derived")

# ---- how strongly the evidence speaks
DIRECT = "direct"              # the value itself, from an authoritative record
LOWER_BOUND = "lower_bound"    # "at least this much" (LinkedIn headcount, a job ad)
PROXY_RANGE = "proxy_range"    # "plausibly between X and Y" (Udyam turnover band)
SEARCH_NEGATIVE = "search_negative"  # we looked and found nothing. NOT the same as a timeout.
EVIDENCE_KINDS = (DIRECT, LOWER_BOUND, PROXY_RANGE, SEARCH_NEGATIVE)


def now_iso() -> str:
    return _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=5, minutes=30))).isoformat(timespec="seconds")


@dataclass
class Source:
    what: str                      # "POST /company/enrich -> employee_count"
    url: Optional[str] = None
    dated: Optional[str] = None    # when the RECORD is from
    fetched: str = field(default_factory=now_iso)  # when WE pulled it
    quote: Optional[str] = None    # the exact passage. Search snippets do not count.
    queries: Optional[list[str]] = None  # for search_negative

    def to_dict(self): return asdict(self)


class UnsourcedFact(ValueError):
    pass


@dataclass
class Fact:
    id: str
    field: str
    value: Any
    origin: str
    status: str
    evidence_kind: Optional[str] = None
    company_match: Optional[str] = None   # company_id | domain | name_city
    source: Optional[Source] = None
    note: str = ""

    def __post_init__(self):
        if self.status not in STATUSES:
            raise ValueError(f"bad status {self.status!r}; expected one of {STATUSES}")
        if self.origin not in ORIGINS:
            raise ValueError(f"bad origin {self.origin!r}; expected one of {ORIGINS}")
        if self.evidence_kind is not None and self.evidence_kind not in EVIDENCE_KINDS:
            raise ValueError(f"bad evidence_kind {self.evidence_kind!r}")
        # THE HARD RULE
        if self.status != CANNOT_VERIFY and self.source is None:
            raise UnsourcedFact(
                f"fact {self.id!r} has status {self.status!r} but no source. "
                "Only cannot_verify may be sourceless."
            )

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d

    # what goes into the decision hash: the claim, not the prose around it
    def hash_key(self) -> tuple:
        return (self.field, repr(self.value), self.status, self.origin)


def declared(fid: str, fld: str, value: Any, words: str) -> Fact:
    """A fact the applicant stated. Its source is their own words."""
    return Fact(id=fid, field=fld, value=value, origin="declared", status=MATCHES,
                evidence_kind=DIRECT,
                source=Source(what="applicant statement", quote=words))


def unverifiable(fid: str, fld: str, why: str) -> Fact:
    return Fact(id=fid, field=fld, value=None, origin="derived",
                status=CANNOT_VERIFY, note=why)
