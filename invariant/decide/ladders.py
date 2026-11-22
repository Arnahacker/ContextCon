"""Fixed fallback ladders: exact -> components -> easiest band / yes-no -> skip. Pure.

"Don't know" (a follow-up fact with status cannot_verify) moves one rung down.
When the same field is asked twice (sum_insured total, then band) the second
answer must use a distinct id, e.g. followup_sum_insured_2."""
from __future__ import annotations

from dataclasses import dataclass, field as dfield
from typing import Optional

from invariant.shapes import Fact

from .derive import si_estimated
from .gate import resolved
from .values import answered, facts_for

OCCUPANCIES = ["leather", "footwear", "garments", "textiles", "food_processing",
               "engineering", "chemicals", "brassware", "other"]
SI_BANDS = ["<1 Cr", "1-5 Cr", "5-25 Cr", "25+ Cr"]


@dataclass(frozen=True)
class Spec:
    field: str
    ask: str
    record_we_need: str
    options: list[str] = dfield(default_factory=list)


_ASSETS = "fire policy schedule or fixed-asset register"
LADDERS: dict[str, list[list[Spec]]] = {
    "occupancy": [[Spec("occupancy", "What does the business mainly make or do?",
                        "Udyam / GST registration activity code", OCCUPANCIES)]],
    "headcount": [[Spec("headcount", "How many people work there in total, including contract workers?",
                        "EPFO / ESIC returns")]],
    "sites": [[Spec("sites", "How many sites or units does the business operate from?",
                    "GST registration (additional places of business)")]],
    "cover_type": [[Spec("cover_type", "Which cover is needed? fire = property (building, machinery, stock); "
                                       "wc = workmen's compensation; fire_wc = both; marine = goods in transit; "
                                       "liability = third-party claims",
                         "the broker's cover request", ["fire", "wc", "fire_wc", "marine", "liability"])]],
    "sum_insured": [
        [Spec("sum_insured", "What total sum insured do you want (building + machinery + stock)?", _ASSETS)],
        [Spec("building_owned", "Is the building owned or rented?", "property papers or rent agreement", ["owned", "rented"]),
         Spec("building_area_sqft", "Roughly what is the built-up area in sq ft?", "building plan or property tax record"),
         Spec("roof_type", "What is the roof made of?", "site photos or survey report", ["concrete", "tin_sheet", "other"]),
         Spec("monthly_sales", "Roughly how much do you sell in a month?", "GST returns (GSTR-3B)"),
         Spec("stock_weeks", "How many weeks of stock do you usually hold?", "stock statement to the bank"),
         Spec("machinery_value", "Roughly what is the machinery worth?", "balance sheet gross block")],
        [Spec("sum_insured", "Which band is the total value in?", _ASSETS, SI_BANDS)],
    ],
    # marine cargo: priced on the value shipped and the route
    "cargo_value": [[Spec("cargo_value", "Roughly what value of goods is shipped in a year (or this shipment, if a one-off)?",
                          "sales invoices / shipping documents")]],
    "marine_route": [[Spec("marine_route", "Are the shipments within India or international?",
                           "shipping documents (bill of lading)", ["domestic", "international"])]],
    # liability: priced on the limit bought and the turnover
    "liability_limit": [[Spec("liability_limit", "What limit of cover is wanted (the most the policy pays per claim)?",
                              "the broker's request", ["50 lakh", "1 Cr", "5 Cr", "10 Cr"])]],
    "turnover": [[Spec("turnover", "What is the annual turnover?", "audited P&L or GST returns")]],
    "claims_history": [[Spec("claims_history", "Any fire, flood or accident claim in the last 5 years?",
                             "insurer claims history (loss run) for the last 5 years", ["yes", "no"])]],
    "wages": [
        [Spec("wages", "What is the annual wage bill?", "wage register or audited P&L")],
        [Spec("pf_monthly", "What is the monthly PF contribution?", "EPFO ECR challans")],
    ],
}


@dataclass(frozen=True)
class LadderState:
    rung: int  # 1-based rung of the pending specs (0 when nothing pending)
    pending: list[Spec]
    skipped: bool  # every rung tried, still nothing


def _followups(facts: list[Fact], field: str) -> int:
    return sum(1 for f in facts_for(facts, field) if f.origin == "applicant_followup")


def _exact(facts: list[Fact], field: str) -> bool:
    """A real (non-derived) answer exists for the field."""
    return any(answered(f) and f.origin != "derived" for f in facts_for(facts, field))


def state(facts: list[Fact], field: str) -> LadderState:
    """First rung with unasked questions. Once the field is resolved (e.g. derived from
    components), the field itself is not re-asked, but unasked components still are:
    they narrow the range."""
    if _exact(facts, field):
        return LadderState(0, [], False)
    done = resolved(facts, field)
    # a sum insured resting on our own building estimate keeps its band question open:
    # answering it replaces the estimate (and its UNDISCLOSED_ESSENTIAL loading)
    estimated = field == "sum_insured" and done and si_estimated(facts)
    band = LADDERS[field][-1][0] if estimated else None
    seen: dict[str, int] = {}
    for i, rung in enumerate(LADDERS[field], start=1):
        pending = []
        for spec in rung:
            seen[spec.field] = seen.get(spec.field, 0) + 1
            if _followups(facts, spec.field) < seen[spec.field] and not (done and spec.field == field and not estimated):
                pending.append(spec)
        if pending:
            if band and band not in pending and _followups(facts, field) < len(LADDERS[field]) - 1:
                pending.append(band)
            return LadderState(i, pending, False)
    return LadderState(0, [], not done)


def skipped_fields(facts: list[Fact]) -> list[str]:
    return [f for f in LADDERS if state(facts, f).skipped]


def spec_for(field: str) -> Optional[Spec]:
    for rungs in LADDERS.values():
        for rung in rungs:
            for s in rung:
                if s.field == field:
                    return s
    return None
