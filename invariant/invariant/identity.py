"""The identity ladder. Plain code: the model never picks a company.

rung 0  a name or domain was given          -> identify, then enrich
rung 1  no name, but enough to narrow it    -> search; one strong match = assumed
rung 2  nothing identifiable                -> check the CLASS, not the company
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Optional

from .facts import Fact, Source, MATCHES, CONTRADICTS, CANNOT_VERIFY, DIRECT, PROXY_RANGE
from .normalize import canonical_name
from .evidence.crustdata import Crustdata, EvidenceUnavailable
from . import adapt

STRONG = 0.80      # a match we will act on
CLOSE = 0.08       # two candidates within this of each other = ambiguous


@dataclass
class Identity:
    rung: int
    company: Optional[dict[str, Any]] = None
    candidates: list[dict[str, Any]] = None
    assumed: bool = False
    cohort_total: int | None = None

    def fact(self) -> Fact:
        if self.company and not self.assumed:
            c = self.company
            return Fact("identity", "company_identity", c.get("company_id"),
                        "crustdata", MATCHES, DIRECT, "company_id",
                        Source(what="POST /company/identify -> company_id",
                               quote=f"{c.get('name')} ({c.get('hq','')})"),
                        note=c.get("tie_break") or "")
        # ambiguity only means something at rung 0: identify returned two CLOSE
        # matches for a name we were given. A broad rung-2 cohort is not that.
        if self.rung == 0 and self.candidates and len(self.candidates) > 1:
            names = " or ".join(f"{c.get('name')} ({c.get('hq','?')})"
                                for c in self.candidates[:4])
            return Fact("identity", "company_identity", None, "crustdata",
                        CONTRADICTS, PROXY_RANGE, None,
                        Source(what="POST /company/identify -> several close matches",
                               quote=names), note=names)
        return Fact("identity", "company_identity", None, "derived", CANNOT_VERIFY,
                    note="the request names no company, domain or city")


def _rank(resp) -> list[dict]:
    """Real shape: [{matches:[{confidence_score, company_data}]}]. See adapt.py."""
    out = []
    for m in adapt.matches(resp):
        cd = m["data"]
        out.append({"company_id": adapt.company_id(cd), "name": adapt.name(cd),
                    "domain": adapt.domain(cd), "hq": adapt.hq(cd),
                    "score": m["confidence"], "_cd": cd})
    return out


def _richest(group: list[dict]) -> dict:
    """Of several profiles of ONE company, the one with the most to check:
    a website domain first, then a recorded size."""
    def score(c):
        cd = c.get("_cd") or {}
        return (bool(c.get("domain")), bool(adapt.employee_range(cd)),
                bool(adapt.profile_url(cd)))
    return sorted(group, key=score, reverse=True)[0]


def break_tie(tied: list[dict], asked: str | None) -> dict | None:
    """Several matches scored the same. Decide only when it is not a guess.

    Live identify returns DUPLICATE PROFILES of one company with equal scores
    ("Gokaldas Exports Limited" and "Gokaldas Exports Ltd.", or two "Snowman
    Logistics Limited" rows, one without a domain). Two cases are safe:

    1. every tied match has the same canonical name -> one company, several
       profiles. Take the richest profile.
    2. exactly one canonical name among the tied matches IS the name the
       broker gave -> that is the company named. Take its richest profile.

    Anything else ("Superhouse Leathers" vs "Superhouse (UK)" for a request
    that said "Superhouse Limited") is genuinely ambiguous and still HOLDS.
    """
    groups: dict[str, list[dict]] = {}
    for c in tied:
        key = canonical_name(c.get("name")) or ""
        if key:
            groups.setdefault(key, []).append(c)
    if not groups:
        return None
    if len(groups) == 1:
        pick = _richest(next(iter(groups.values())))
        return {**pick, "tie_break": f"{len(tied)} profiles of the same company; "
                                     f"used the one with the most data"}
    want = canonical_name(asked) or ""
    exact = groups.get(want)
    if exact:
        pick = _richest(exact)
        others = ", ".join(sorted(k for k in groups if k != want))
        return {**pick, "tie_break": f"exact match for the name given; also seen: {others}"}
    return None


EXACT_FLOOR = 0.50   # an exact legal-name match counts down to this score


def exact_name_match(cands: list[dict], asked: str | None, top: dict) -> dict | None:
    """The broker gave a legal name and the top-scored match is NOT it.

    Seen live: "Sudarshan Chemical Industries Limited" -> top 0.80 is the plant
    profile "...Limited, Roha And Mahad" (51-200 staff, no domain); the company
    itself, "Sudarshan Chemical Industries Ltd.", scores 0.60. Equality with
    the name given is not a guess, a fuzzy score is. Only when exactly ONE
    company has that exact name; otherwise the normal rules apply.
    """
    want = canonical_name(asked) or ""
    if not want or canonical_name(top.get("name")) == want:
        return None
    exact = [c for c in cands
             if canonical_name(c.get("name")) == want and c.get("score", 0) >= EXACT_FLOOR]
    if not exact:
        return None
    pick = _richest(exact)
    return {**pick, "tie_break": f"exact match for the name given, preferred over "
                                 f"higher-scored '{top.get('name')}'"}


def resolve(form, crust: Crustdata) -> Identity:
    # ---- rung 0
    if form.company_name or getattr(form, "domain", None):
        try:
            cands = _rank(crust.identify(names=[form.company_name]))
        except EvidenceUnavailable:
            raise
        if cands:
            top = cands[0]
            exact = exact_name_match(cands, form.company_name, top)
            if exact is not None:
                return Identity(rung=0, company=exact, candidates=cands[:5])
            tied = [c for c in cands if top.get("score", 0) - c.get("score", 0) < CLOSE]
            if top.get("score", 0) >= STRONG:
                if len(tied) == 1:
                    return Identity(rung=0, company=top, candidates=cands[:5])
                pick = break_tie(tied, form.company_name)
                if pick is not None:
                    return Identity(rung=0, company=pick, candidates=cands[:5])
            return Identity(rung=0, company=None, candidates=cands[:5])

    # ---- rung 1: no name. Narrow by what we do know.
    if form.industry and (form.countries or form.declared_sites):
        filters = {"op": "and", "conditions": [
            {"field": "taxonomy.professional_network_industry", "type": "(.)",
             "value": form.industry},
        ]}
        if form.countries:
            filters["conditions"].append(
                {"field": "locations.country", "type": "=", "value": "India"})
        try:
            resp = crust.company_search(
                filters, limit=25,
                fields=["basic_info.name", "basic_info.primary_domain",
                        "headcount.total", "locations.headquarters"])
        except EvidenceUnavailable:
            raise
        cands = resp.get("companies") or resp.get("results") or []
        for c in cands:            # company/search returns flat rows, not matches
            c.setdefault("name", c.get("basic_info.name"))
            c.setdefault("company_id", c.get("crustdata_company_id"))
        if len(cands) == 1:
            return Identity(rung=1, company=cands[0], candidates=cands, assumed=True)
        return Identity(rung=2, company=None, candidates=cands[:6],
                        cohort_total=resp.get('total') or len(cands))

    # ---- rung 2
    return Identity(rung=2, company=None, candidates=[])
