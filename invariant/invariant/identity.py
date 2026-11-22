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
                               quote=f"{c.get('name')} ({c.get('hq','')})"))
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


def resolve(form, crust: Crustdata) -> Identity:
    # ---- rung 0
    if form.company_name or getattr(form, "domain", None):
        try:
            cands = _rank(crust.identify(names=[form.company_name]))
        except EvidenceUnavailable:
            raise
        if cands:
            top = cands[0]
            second = cands[1] if len(cands) > 1 else None
            close = second and (top.get("score", 0) - second.get("score", 0)) < CLOSE
            if top.get("score", 0) >= STRONG and not close:
                return Identity(rung=0, company=top, candidates=cands[:5])
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
