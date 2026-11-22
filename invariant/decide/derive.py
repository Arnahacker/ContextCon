"""Derived facts from follow-up components (fallback ladders). Pure.

Every derived value is a Fact with origin "derived", a Derivation (formula, inputs,
range) and a Source whose quote is the worked example. Value = midpoint of the range."""
from __future__ import annotations

from typing import Optional

from invariant.shapes import Derivation, Fact, Source

from . import norms
from .values import answered, as_bool, facts_for, headcount, inr, mid, num_range, occupancy, pick

Range = tuple[float, float]


def _fact(field: str, formula: str, inputs: list[Fact], rng: Range, quote: str) -> Fact:
    stamps = [f.source.fetched for f in inputs if f.source]
    return Fact(
        id=f"derived_{field}", field=field, value=int(round(mid(rng))),
        origin="derived", evidence_kind="proxy_range", status="consistent_unconfirmed",
        source=Source(what=f"derived: {formula}", quote=quote, fetched=max(stamps) if stamps else "", dated=None),
        derivation=Derivation(formula=formula, inputs=[f.id for f in inputs], range=(float(rng[0]), float(rng[1]))),
    )


def _followup(facts: list[Fact], field: str) -> Optional[Fact]:
    """The latest follow-up fact for a field (answered or not)."""
    fs = [f for f in facts_for(facts, field) if f.origin == "applicant_followup"]
    return fs[-1] if fs else None


def _direct(facts: list[Fact], field: str) -> Optional[tuple[Fact, Range]]:
    f = pick(facts, field)
    r = num_range(f.value) if f else None
    return (f, r) if r else None


def sum_insured_ladder_active(facts: list[Fact]) -> bool:
    """Components are only derived once the applicant could not give the total."""
    if any(answered(f) and f.origin in ("declared", "applicant_followup") for f in facts_for(facts, "sum_insured")):
        return False
    return any(f.origin == "applicant_followup" and f.status == "cannot_verify"
               for f in facts_for(facts, "sum_insured"))


def _building(facts: list[Fact]) -> Optional[Fact]:
    if _direct(facts, "building_value"):
        return None  # direct answer is used as-is
    owned_f = _followup(facts, "building_owned")
    if owned_f is None:
        return None
    owned = as_bool(owned_f.value) if answered(owned_f) else None
    if owned is False:
        return _fact("building_value", "0 (building not owned)", [owned_f], (0, 0), "Rs 0 = building rented, not owned")
    area_f = pick(facts, "building_area_sqft")
    area = num_range(area_f.value) if area_f else None
    if not area:
        return None
    roof_f = pick(facts, "roof_type")
    roof = roof_f.value if roof_f and roof_f.value in norms.COST_PER_SQFT else None
    costs = [norms.COST_PER_SQFT[roof]] if roof else list(norms.COST_PER_SQFT.values())
    lo, hi = area[0] * min(costs), area[1] * max(costs)
    inputs = [owned_f, area_f] + ([roof_f] if roof_f else [])
    roof_txt = f"Rs {costs[0]:,}/sq ft ({roof})" if roof else f"Rs {min(costs):,}-{max(costs):,}/sq ft (roof unknown)"
    quote = f"{inr(mid((lo, hi)))} = {mid(area):,.0f} sq ft x {roof_txt}; {norms.LABEL}"
    return _fact("building_value", "building_area_sqft * cost_per_sqft[roof_type]", inputs, (lo, hi), quote)


def _stock(facts: list[Fact], occ: Optional[str]) -> Optional[Fact]:
    if _direct(facts, "stock_value"):
        return None
    sales_f = pick(facts, "monthly_sales")
    sales = num_range(sales_f.value) if sales_f else None
    if not sales:
        return None
    weeks_f = pick(facts, "stock_weeks")
    weeks = num_range(weeks_f.value) if weeks_f else None
    inputs = [sales_f] + ([weeks_f] if weeks else [])
    if not weeks:
        weeks = tuple(float(w) for w in norms.stock_weeks(occ))
        wk_txt = f"{weeks[0]:.0f}-{weeks[1]:.0f} weeks ({occ or 'other'} norm, {norms.LABEL})"
    else:
        wk_txt = f"{mid(weeks):g} weeks"
    lo = sales[0] * weeks[0] / norms.WEEKS_PER_MONTH
    hi = sales[1] * weeks[1] / norms.WEEKS_PER_MONTH
    quote = f"{inr(mid((lo, hi)))} = {inr(mid(sales))}/month x {wk_txt} / 4.3"
    return _fact("stock_value", "monthly_sales * stock_weeks / 4.3", inputs, (lo, hi), quote)


def _machinery(facts: list[Fact], occ: Optional[str]) -> Optional[Fact]:
    if _direct(facts, "machinery_value"):
        return None
    hc = headcount(facts)
    if hc is None:
        return None
    hc_facts = [f for f in facts_for(facts, "headcount") if answered(f)]
    per_lo, per_hi = norms.machinery_per_worker(occ)
    lo, hi = hc * per_lo, hc * per_hi
    quote = (f"{inr(mid((lo, hi)))} = {hc:,.0f} workers x Rs {per_lo / norms.LAKH:g}-{per_hi / norms.LAKH:g} lakh "
             f"per worker ({occ or 'other'} norm, {norms.LABEL})")
    return _fact("machinery_value", "headcount * capital_per_worker", hc_facts, (lo, hi), quote)


def _wages(facts: list[Fact]) -> Optional[Fact]:
    if pick(facts, "wages"):
        return None
    pf_f = pick(facts, "pf_monthly")
    pf = num_range(pf_f.value) if pf_f else None
    if not pf:
        return None
    lo, hi = pf[0] / norms.PF_RATE * 12, pf[1] / norms.PF_RATE * 12
    quote = f"{inr(mid((lo, hi)))} = {inr(mid(pf))} PF per month / 0.12 x 12"
    return _fact("wages", "pf_monthly / 0.12 * 12", [pf_f], (lo, hi), quote)


def derive(facts: list[Fact]) -> list[Fact]:
    """All derived facts implied by the given (non-derived) facts."""
    facts = [f for f in facts if f.origin != "derived"]
    occ = occupancy(facts)
    out: list[Fact] = []
    if sum_insured_ladder_active(facts):
        parts: list[tuple[Fact, Range]] = []
        for field, fn in (("building_value", lambda: _building(facts)),
                          ("machinery_value", lambda: _machinery(facts, occ)),
                          ("stock_value", lambda: _stock(facts, occ))):
            d = _direct(facts, field)
            if d:
                parts.append(d)
                continue
            f = fn()
            if f:
                out.append(f)
                parts.append((f, f.derivation.range))
        if len(parts) == 3:
            lo = sum(r[0] for _, r in parts)
            hi = sum(r[1] for _, r in parts)
            quote = (f"{inr(mid((lo, hi)))} = building {inr(mid(parts[0][1]))} + machinery {inr(mid(parts[1][1]))}"
                     f" + stock {inr(mid(parts[2][1]))}")
            out.append(_fact("sum_insured", "building_value + machinery_value + stock_value",
                             [f for f, _ in parts], (lo, hi), quote))
    if w := _wages(facts):
        out.append(w)
    return out
