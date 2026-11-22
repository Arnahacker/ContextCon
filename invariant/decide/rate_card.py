"""ILLUSTRATIVE rate card -- placeholder rates for the demo, not a filed tariff."""
from __future__ import annotations

from typing import Optional

LABEL = "illustrative rate card (placeholder, not a filed tariff)"

FIRE_PER_MILLE = {
    "leather": 1.20, "footwear": 0.90, "garments": 0.80, "textiles": 1.00, "food_processing": 0.70,
    "engineering": 0.60, "chemicals": 1.65, "brassware": 0.75, "other": 1.00,
}
STFI_PER_MILLE = 0.15
WC_PER_100 = {
    "leather": 4.0, "footwear": 3.0, "garments": 2.5, "textiles": 3.0, "food_processing": 3.0,
    "engineering": 5.0, "chemicals": 6.0, "brassware": 3.5, "other": 3.5,
}
# marine cargo: insured value = cargo value x 110% (CIF + 10%), rate in % of insured value
MARINE_PCT = {
    "leather": 0.25, "footwear": 0.20, "garments": 0.20, "textiles": 0.20, "food_processing": 0.35,
    "engineering": 0.25, "chemicals": 0.50, "brassware": 0.20, "other": 0.30,
}
MARINE_ROUTE = {"domestic": 1.0, "international": 1.5}
# liability: rate on the limit of indemnity (%), adjusted for turnover
LIABILITY_ROL_PCT = {
    "leather": 1.5, "footwear": 1.0, "garments": 0.8, "textiles": 1.0, "food_processing": 1.2,
    "engineering": 1.2, "chemicals": 2.5, "brassware": 1.0, "other": 1.2,
}
LIABILITY_TURNOVER = [(10 * 10**7, 1.0), (100 * 10**7, 1.25), (float("inf"), 1.6)]  # up to 10 Cr, 100 Cr, more

MIN_PREMIUM = 10_000
GST = 0.18

# named loadings (multipliers)
LOADINGS = {
    "HEADCOUNT_UNDERSTATED": 1.35,
    "UNDECLARED_SITE": 1.10,
    "UNDECLARED_HAZARD": 1.25,
    "ADVERSE_EVENT": 1.30,
    "CLAIMS_HISTORY_UNKNOWN": 1.15,
    "DERIVED_VALUE": 1.05,
    "UNKNOWN": 1.15,  # UNKNOWN_<FIELD>
    # applicant said "don't know" to information only they hold (building, sum insured band,
    # or an essential field with no record), so we priced on our own estimate
    "UNDISCLOSED_ESSENTIAL": 1.25,
}

Triple = tuple[float, float, float]  # (low, mid, high)


def _one(cover: str, occ: str, si: Optional[float], wages: Optional[float], mult: float) -> int:
    base = 0.0
    if cover in ("fire", "fire_wc"):
        base += (si or 0) * (FIRE_PER_MILLE.get(occ, FIRE_PER_MILLE["other"]) + STFI_PER_MILLE) / 1000
    if cover in ("wc", "fire_wc"):
        base += (wages or 0) * WC_PER_100.get(occ, WC_PER_100["other"]) / 100
    net = max(base * mult, MIN_PREMIUM)
    return int(round(net * (1 + GST)))


def _gst(net: float) -> int:
    return int(round(max(net, MIN_PREMIUM) * (1 + GST)))


def price_marine(occ: str, cargo: Triple, route: str, mult: float) -> Triple:
    rate = MARINE_PCT.get(occ, MARINE_PCT["other"]) / 100 * MARINE_ROUTE.get(route, MARINE_ROUTE["international"])
    return tuple(_gst(v * 1.10 * rate * mult) for v in cargo)  # type: ignore[return-value]


def liability_turnover_factor(turnover: float) -> float:
    return next(f for cap, f in LIABILITY_TURNOVER if turnover <= cap)


def price_liability(occ: str, limit: float, turnover: Triple, mult: float) -> Triple:
    rol = LIABILITY_ROL_PCT.get(occ, LIABILITY_ROL_PCT["other"]) / 100
    return tuple(_gst(limit * rol * liability_turnover_factor(t) * mult) for t in turnover)  # type: ignore[return-value]


def price(cover: str, occ: str, si: Optional[Triple], wages: Optional[Triple], mult: float) -> Triple:
    """Premium incl. GST as (low, mid, high) from the input ranges."""
    return tuple(_one(cover, occ, si[i] if si else None, wages[i] if wages else None, mult)
                 for i in range(3))  # type: ignore[return-value]
