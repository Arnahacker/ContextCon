"""How the premium was built, line by line. Pure, like the rest of decide/.

Replays the rate card on the mid values the engine priced on: base(s) -> each named
loading in the order the engine applied it -> minimum premium -> GST. The total must
equal the engine's own mid premium to the rupee; if it ever does not, return None so
the screen never shows a breakdown that disagrees with the decision.
"""
from __future__ import annotations

from typing import Optional

from invariant.shapes import Fact

from . import derive as derive_mod, rate_card
from .engine import assess
from .values import fact_range, mid, occupancy, pick

# names a broker understands, for the base lines and the loadings
OCC_LABEL = {"food_processing": "food processing"}
LOADING_LABEL = {
    "HEADCOUNT_UNDERSTATED": "Staff count understated", "UNDECLARED_SITE": "Undeclared location",
    "UNDECLARED_HAZARD": "Undeclared hazardous work", "DISCLOSED_HAZARD": "Hazardous work (disclosed)",
    "ADVERSE_EVENT": "Adverse news", "CLAIMS_HISTORY_UNKNOWN": "Past claims unknown",
    "DERIVED_VALUE": "Estimated values margin", "UNDISCLOSED_ESSENTIAL": "Essential information not given",
    "OCCUPANCY_MISMATCH": "Riskier line of business on record",
}


def _label(rule: str) -> str:
    if rule.startswith("UNKNOWN_"):
        return f"Unknown: {rule[8:].lower().replace('_', ' ')}"
    return LOADING_LABEL.get(rule, rule.replace("_", " ").capitalize())


def _bases(a, facts: list[Fact]) -> Optional[list[dict]]:
    occ = occupancy(facts) or "other"
    occ_name = OCC_LABEL.get(occ, occ)
    out: list[dict] = []
    if a.cover in ("fire", "fire_wc"):
        si = fact_range(pick(facts, "sum_insured"))
        if not si:
            return None
        s = mid(si)
        rate = rate_card.FIRE_PER_MILLE.get(occ, rate_card.FIRE_PER_MILLE["other"])
        out.append({"label": f"Fire ({occ_name}): {rate}‰ of sum insured", "amount": s * rate / 1000,
                    "basis": s, "basis_label": "sum insured"})
        out.append({"label": f"Natural perils (STFI): {rate_card.STFI_PER_MILLE}‰ of sum insured",
                    "amount": s * rate_card.STFI_PER_MILLE / 1000, "basis": s, "basis_label": "sum insured"})
    if a.cover in ("wc", "fire_wc"):
        if not a.wages:
            return None
        w = a.wages[1]
        rate = rate_card.WC_PER_100.get(occ, rate_card.WC_PER_100["other"])
        out.append({"label": f"Workmen's comp ({occ_name}): {rate}% of wages", "amount": w * rate / 100,
                    "basis": w, "basis_label": "yearly wages"})
    if a.cover == "marine":
        cargo = fact_range(pick(facts, "cargo_value"))
        route_f = pick(facts, "marine_route")
        route = str(route_f.value) if route_f else "international"
        pct = rate_card.MARINE_PCT.get(occ, rate_card.MARINE_PCT["other"])
        rf = rate_card.MARINE_ROUTE.get(route, rate_card.MARINE_ROUTE["international"])
        c = mid(cargo)
        out.append({"label": f"Marine cargo ({occ_name}): {pct}% x {rf} ({route}) of cargo + 10%",
                    "amount": c * 1.10 * pct / 100 * rf, "basis": c, "basis_label": "cargo value"})
    if a.cover == "liability":
        limit = mid(fact_range(pick(facts, "liability_limit")))
        turnover = mid(derive_mod.usable_turnover(facts))
        rol = rate_card.LIABILITY_ROL_PCT.get(occ, rate_card.LIABILITY_ROL_PCT["other"])
        tf = rate_card.liability_turnover_factor(turnover)
        out.append({"label": f"Liability ({occ_name}): {rol}% of the limit x {tf} for turnover",
                    "amount": limit * rol / 100 * tf, "basis": limit, "basis_label": "limit of cover"})
    return out or None


def breakdown(raw: list[Fact]) -> Optional[dict]:
    """Line items from base to the final premium incl. GST, or None when not priced."""
    a = assess(list(raw))
    if a.premium is None:
        return None
    facts = a.facts
    bases = _bases(a, facts)
    if not bases:
        return None

    lines: list[dict] = []
    running = 0.0
    for b in bases:
        running += b["amount"]
        lines.append({"kind": "base", "label": b["label"], "rule": None, "multiplier": None,
                      "amount": round(b["amount"]), "running": round(running),
                      "basis": round(b["basis"]), "basis_label": b["basis_label"]})

    # loadings in the engine's order; repeated rules (e.g. several sites) are grouped
    grouped: list[tuple[str, float, list[str]]] = []
    for s in a.steps:
        if s.multiplier == 1.0:
            continue
        if grouped and grouped[-1][0] == s.rule:
            r, m, because = grouped[-1]
            grouped[-1] = (r, m * s.multiplier, because + list(s.because))
        else:
            grouped.append((s.rule, s.multiplier, list(s.because)))
    for rule, m, because in grouped:
        before = running
        running *= m
        lines.append({"kind": "loading", "label": _label(rule), "rule": rule, "multiplier": round(m, 4),
                      "amount": round(running - before), "running": round(running),
                      "because": list(dict.fromkeys(because))})

    if running < rate_card.MIN_PREMIUM:
        lines.append({"kind": "minimum", "label": "Minimum premium", "rule": None, "multiplier": None,
                      "amount": round(rate_card.MIN_PREMIUM - running), "running": rate_card.MIN_PREMIUM})
        running = float(rate_card.MIN_PREMIUM)

    total = int(round(running * (1 + rate_card.GST)))
    lines.append({"kind": "gst", "label": f"GST {int(rate_card.GST * 100)}%", "rule": None, "multiplier": None,
                  "amount": total - round(running), "running": total})

    if total != a.premium[1]:  # never show a breakdown that disagrees with the decision
        return None
    return {"cover": a.cover, "total": total, "range": [a.premium[0], a.premium[2]],
            "lines": lines, "rate_card": rate_card.LABEL}
