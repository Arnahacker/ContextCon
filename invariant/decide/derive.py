"""Derived facts from follow-up components (fallback ladders). Pure.

Every derived value is a Fact with origin "derived", a Derivation (formula, inputs,
range) and a Source whose quote is the worked example. Value = midpoint of the range."""
from __future__ import annotations

from typing import Optional

from invariant.shapes import Derivation, Fact, Source

from . import norms
from .values import answered, as_bool, crore, facts_for, headcount, inr, mid, num_range, occupancy, pick

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


def _unknown(facts: list[Fact], field: str) -> Optional[Fact]:
    """The applicant's latest follow-up for a field when it was "don't know" and nothing
    else gives a value."""
    f = _followup(facts, field)
    if f is not None and not answered(f) and pick(facts, field) is None:
        return f
    return None


def _hc_facts(facts: list[Fact]) -> list[Fact]:
    return [f for f in facts_for(facts, "headcount") if answered(f)]


def _building(facts: list[Fact]) -> Optional[Fact]:
    """Rented -> 0. Owned + area -> area x cost. When the applicant does not know the area
    (or whether it is owned), the area is estimated from headcount; unknown ownership makes
    the range start at Rs 0."""
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
    estimated = False
    if not area:
        if owned is True and _unknown(facts, "building_area_sqft") is None:
            return None  # owned; the area question is still to be answered
        hc = headcount(facts)
        if hc is None:
            return None
        area = (hc * norms.SQFT_PER_WORKER[0], hc * norms.SQFT_PER_WORKER[1])
        estimated = True
    roof_f = pick(facts, "roof_type")
    roof = roof_f.value if roof_f and roof_f.value in norms.COST_PER_SQFT else None
    costs = [norms.COST_PER_SQFT[roof]] if roof else list(norms.COST_PER_SQFT.values())
    lo, hi = area[0] * min(costs), area[1] * max(costs)
    if owned is None:
        lo = 0.0
    inputs = [owned_f] + ([area_f] if area_f else []) + ([roof_f] if roof_f else [])
    inputs += [f for f in ([_followup(facts, "building_area_sqft")] if estimated else []) if f and f not in inputs]
    inputs += _hc_facts(facts) if estimated else []
    roof_txt = f"Rs {costs[0]:,}/sq ft ({roof})" if roof else f"Rs {min(costs):,}-{max(costs):,}/sq ft (roof unknown)"
    area_txt = f"{mid(area):,.0f} sq ft"
    if estimated:
        area_txt += (f" (estimated: {headcount(facts):,.0f} workers x {norms.SQFT_PER_WORKER[0]}-"
                     f"{norms.SQFT_PER_WORKER[1]} sq ft per worker)")
    quote = f"{inr(mid((lo, hi)))} = {area_txt} x {roof_txt}"
    if owned is None:
        quote += "; ownership not known, so the range starts at Rs 0"
    quote += f"; {norms.LABEL}"
    formula = ("headcount * sqft_per_worker * cost_per_sqft[roof_type]" if estimated
               else "building_area_sqft * cost_per_sqft[roof_type]")
    return _fact("building_value", formula, inputs, (lo, hi), quote)


def usable_turnover(facts: list[Fact]) -> Optional[Range]:
    """Turnover we can price on: the applicant's, our estimate, or a record band tight enough to use."""
    f = pick(facts, "turnover")
    if f and f.origin in ("applicant_followup", "declared", "derived"):
        return f.derivation.range if f.derivation else num_range(f.value)
    rec = _record_revenue(facts)
    return rec[1] if rec else None


def _record_revenue(facts: list[Fact]) -> Optional[tuple[Fact, Range]]:
    """Annual turnover from any source, if its band is tight enough to estimate from."""
    f = pick(facts, "turnover")
    r = num_range(f.value) if f else None
    if not r or r[0] <= 0 or r[1] / r[0] > norms.MAX_REVENUE_RATIO:
        return None
    return f, r


def _monthly_sales(facts: list[Fact], occ: Optional[str]) -> Optional[tuple[list[Fact], Range, str]]:
    """Applicant's answer, else the record's revenue / 12, else headcount x sales-per-worker norm."""
    sales_f = pick(facts, "monthly_sales")
    sales = num_range(sales_f.value) if sales_f else None
    if sales:
        return [sales_f], sales, f"{inr(mid(sales))}/month"
    rec = _record_revenue(facts)
    if rec:
        f, (lo, hi) = rec
        sales = (lo / 12, hi / 12)
        return [f], sales, f"{inr(mid(sales))}/month (turnover {inr(lo)}-{inr(hi)} / 12)"
    hc = headcount(facts)
    if hc is None:
        return None
    per_lo, per_hi = norms.revenue_per_worker(occ)
    sales = (hc * per_lo / 12, hc * per_hi / 12)
    txt = (f"{inr(mid(sales))}/month (estimated: {hc:,.0f} workers x Rs {per_lo / norms.LAKH:g}-"
           f"{per_hi / norms.LAKH:g} lakh sales per worker a year / 12, {occ or 'other'} norm)")
    return _hc_facts(facts), sales, txt


def underinsurance(facts: list[Fact]) -> Optional[str]:
    """Plausibility check of the applicant's sum insured: below half of a conservative
    record-based floor (machinery + stock only, building left out) is flagged."""
    facts = [f for f in facts if f.origin != "derived"]
    si_f = next((f for f in sorted(facts_for(facts, "sum_insured"), key=lambda f: f.origin != "applicant_followup")
                 if answered(f) and f.origin in ("declared", "applicant_followup")), None)
    si = num_range(si_f.value) if si_f else None
    if not si or headcount(facts) is None:
        return None
    occ = occupancy(facts)
    m, s = _machinery(facts, occ), _stock(facts, occ)
    if not (m and s):
        return None
    floor = m.derivation.range[0] + s.derivation.range[0]
    if si[1] >= floor / 2:
        return None
    return (f"underinsurance: the applicant asks to insure {crore(si[1])}, but a company this size usually "
            f"holds at least {crore(floor)} in machinery and stock alone (machinery {crore(m.derivation.range[0])} "
            f"+ stock {crore(s.derivation.range[0])}, estimated from the record headcount; building not counted; "
            f"illustrative norms)")


def monthly_sales_estimate(facts: list[Fact]) -> Optional[Range]:
    """Our current monthly-sales range when the applicant has not given one (for pricing the question)."""
    facts = [f for f in facts if f.origin != "derived"]
    if pick(facts, "monthly_sales"):
        return None
    got = _monthly_sales(facts + _tier1_fallbacks(facts), occupancy(facts))
    return got[1] if got else None


def _stock(facts: list[Fact], occ: Optional[str]) -> Optional[Fact]:
    if _direct(facts, "stock_value"):
        return None
    got = _monthly_sales(facts, occ)
    if not got:
        return None
    inputs, sales, sales_txt = got
    weeks_f = pick(facts, "stock_weeks")
    weeks = num_range(weeks_f.value) if weeks_f else None
    inputs = list(inputs) + ([weeks_f] if weeks else [])
    if not weeks:
        weeks = tuple(float(w) for w in norms.stock_weeks(occ))
        wk_txt = f"{weeks[0]:.0f}-{weeks[1]:.0f} weeks ({occ or 'other'} norm, {norms.LABEL})"
    else:
        wk_txt = f"{mid(weeks):g} weeks"
    lo = sales[0] * weeks[0] / norms.WEEKS_PER_MONTH
    hi = sales[1] * weeks[1] / norms.WEEKS_PER_MONTH
    quote = f"{inr(mid((lo, hi)))} = {sales_txt} x {wk_txt} / 4.3"
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


def _exhausted(facts: list[Fact], field: str) -> Optional[Fact]:
    """A one-rung Tier 1 field the applicant could not answer and no record fills."""
    if any(answered(f) for f in facts_for(facts, field)):
        return None
    return _unknown(facts, field)


def _tier1_fallbacks(facts: list[Fact]) -> list[Fact]:
    """Last-resort values so a "don't know" never leaves the case stuck. Each is a derived
    fact with its working; the ones only the applicant could know carry the
    UNDISCLOSED_ESSENTIAL loading (see undisclosed())."""
    out: list[Fact] = []
    if f := _exhausted(facts, "cover_type"):
        out.append(_fact_value("cover_type", "default: fire (property) cover", [f], "fire",
                               "fire = broker did not say which cover, so the property (fire) cover is priced"))
    if f := _exhausted(facts, "occupancy"):
        out.append(_fact_value("occupancy", "default: other", [f], "other",
                               "other = activity not known and not in the record; highest-uncertainty band"))
    if f := _exhausted(facts, "sites"):
        out.append(_fact("sites", "default: 1 site", [f], (1, 1), "1 = number of sites not known and not in the record"))
    # marine / liability: values only the applicant knows; cautious defaults carry the penalty
    if f := _exhausted(facts, "marine_route"):
        out.append(_fact_value("marine_route", "default: international (the dearer route)", [f], "international",
                               "international = route not known, so the dearer (international) rate is used"))
    if f := _exhausted(facts, "liability_limit"):
        out.append(_fact("liability_limit", "default: Rs 1 Cr limit", [f], (10_000_000, 10_000_000),
                         "Rs 1 Cr = limit not given; a standard Rs 1 Cr limit is priced"))
    sales = _monthly_sales(facts, occupancy(facts))
    if (f := _exhausted(facts, "cargo_value")) and sales:
        inputs, (lo, hi), txt = sales
        out.append(_fact("cargo_value", "monthly_sales * 12", [f] + list(inputs), (lo * 12, hi * 12),
                         f"{inr(mid((lo * 12, hi * 12)))} a year = {txt} x 12 (everything sold is assumed shipped)"))
    if (f := _unknown(facts, "turnover")) and usable_turnover(facts) is None and sales:
        inputs, (lo, hi), txt = sales
        out.append(_fact("turnover", "monthly_sales * 12", [f] + list(inputs), (lo * 12, hi * 12),
                         f"{inr(mid((lo * 12, hi * 12)))} a year = {txt} x 12"))
    if f := _exhausted(facts, "headcount"):
        sites_f = pick(facts + out, "sites")
        n = mid(num_range(sites_f.value) or (1, 1)) if sites_f else 1
        if sites_f and sites_f.derivation:
            n = mid(sites_f.derivation.range)
        lo, hi = n * norms.HEADCOUNT_PER_SITE[0], n * norms.HEADCOUNT_PER_SITE[1]
        inputs = [f] + ([sites_f] if sites_f else [])
        out.append(_fact("headcount", "sites * workers_per_site", inputs, (lo, hi),
                         f"{mid((lo, hi)):,.0f} = {n:g} site(s) x {norms.HEADCOUNT_PER_SITE[0]}-"
                         f"{norms.HEADCOUNT_PER_SITE[1]} workers per site ({norms.LABEL})"))
    return out


def _fact_value(field: str, formula: str, inputs: list[Fact], value, quote: str) -> Fact:
    """A derived non-numeric value (e.g. a default cover)."""
    stamps = [f.source.fetched for f in inputs if f.source]
    return Fact(id=f"derived_{field}", field=field, value=value, origin="derived", evidence_kind="proxy_range",
                status="consistent_unconfirmed",
                source=Source(what=f"derived: {formula}", quote=quote, fetched=max(stamps) if stamps else "", dated=None),
                derivation=Derivation(formula=formula, inputs=[f.id for f in inputs], range=(0.0, 0.0)))


def undisclosed(facts: list[Fact]) -> list[Fact]:
    """The applicant's "don't know" answers that forced us to price on our own estimate of
    information only they hold: building ownership / area and the sum-insured band (once the
    total was not known), or an essential field with no record at all."""
    facts = [f for f in facts if f.origin != "derived"]
    out = [f for field in ("occupancy", "headcount", "sites", "cargo_value", "marine_route", "liability_limit")
           if (f := _exhausted(facts, field))]
    if sum_insured_ladder_active(facts):
        owned_f = _followup(facts, "building_owned")
        if owned_f is not None and not answered(owned_f):
            out.append(owned_f)
        elif owned_f is not None and as_bool(owned_f.value) is True and (a := _unknown(facts, "building_area_sqft")):
            out.append(a)
        sis = [f for f in facts_for(facts, "sum_insured") if f.origin == "applicant_followup"]
        if len(sis) >= 2 and not answered(sis[-1]):  # the band question, after the total
            out.append(sis[-1])
    return out


def si_estimated(facts: list[Fact]) -> bool:
    """The derived sum insured rests on our estimate of the building (not the applicant's)."""
    return any(f.field in ("building_owned", "building_area_sqft") for f in undisclosed(facts))


def derive(facts: list[Fact]) -> list[Fact]:
    """All derived facts implied by the given (non-derived) facts."""
    facts = [f for f in facts if f.origin != "derived"]
    out: list[Fact] = _tier1_fallbacks(facts)
    facts = facts + out  # a fallback headcount feeds the machinery / stock estimates
    occ = occupancy(facts)
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
