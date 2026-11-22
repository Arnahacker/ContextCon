"""Provisional values, so a blocked case still shows a number.

Every value here is origin="derived". By the rule in decide.resolved(), a
derived value can move a provisional premium but can never clear the intake
gate and can never cause a decline. It is labelled "assumed" on screen.
"""
from __future__ import annotations
from .facts import Fact, Source, MATCHES
from .decide import resolved, value_of

# very rough sum insured per head, by occupancy. Illustrative only.
SI_PER_HEAD = {
    "office": 150_000, "retail_shop": 300_000, "hotel_restaurant": 400_000,
    "hospital_clinic": 600_000, "electronics_assembly": 450_000,
    "engineering_workshop": 500_000, "light_manufacturing": 350_000,
    "food_processing": 450_000, "pharmaceutical": 700_000,
    "garment_stitching": 250_000, "printing_paper": 450_000, "warehouse": 400_000,
    "cold_storage": 800_000, "furniture_wood": 350_000, "textile_mill": 600_000,
    "plastics_rubber": 500_000, "leather_tanning": 450_000,
    "foundry_forging": 650_000, "chemical_processing": 600_000,
    "unknown": 300_000,
}
DEFAULT_HEADCOUNT = 50


def assume_for_pricing(facts: list[Fact]) -> list[Fact]:
    """Return facts plus derived stand-ins for anything missing that blocks pricing."""
    out = list(facts)

    if not resolved(out, "cover_type"):
        out.append(Fact("assumed_cover", "cover_type", "fire", "derived", MATCHES,
                        "proxy_range", None,
                        Source(what="assumed: fire is the default commercial line"),
                        note="assumed"))

    if not resolved(out, "occupancy"):
        out.append(Fact("assumed_occ", "occupancy", "unknown", "derived", MATCHES,
                        "proxy_range", None,
                        Source(what="assumed: occupancy not established"), note="assumed"))

    if not resolved(out, "sum_insured_inr"):
        occ = value_of(out, "occupancy", "unknown")
        head = value_of(out, "headcount") or DEFAULT_HEADCOUNT
        per = SI_PER_HEAD.get(occ, SI_PER_HEAD["unknown"])
        est = int(head) * per
        out.append(Fact("assumed_si", "sum_insured_inr", est, "derived", MATCHES,
                        "proxy_range", None,
                        Source(what=f"assumed: {head} staff x Rs {per:,}/head for {occ}"),
                        note="assumed"))
    return out
