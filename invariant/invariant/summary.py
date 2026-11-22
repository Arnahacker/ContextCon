"""Plain English, generated from the facts. No model: this must stay
deterministic or it breaks the invariance guarantee.

The screen is read by an underwriter in a hurry, not by an engineer.
"""
from __future__ import annotations
from typing import Any

MONEY = lambda n: "Rs " + format(int(n or 0), ",d")

FIELD_NAMES = {
    "headcount": "staff numbers", "sites": "number of premises",
    "undeclared_site": "an extra location", "undeclared_hazard": "a hazardous process",
    "occupancy": "what happens on site", "sum_insured_inr": "the sum insured",
    "cover_type": "the type of cover", "company_identity": "which company this is",
    "claims_history": "past claims", "construction": "how the building is built",
    "protection": "fire protection", "adverse_event": "past incidents",
    "certification": "a safety certificate", "class_benchmark": "size for this trade",
    "class_percentile": "size for this trade", "headcount_growth_pct": "growth rate",
    "staff_abroad": "staff in another country", "hiring_location": "a hiring location",
    "hiring_abroad": "hiring abroad",
}

VERDICT = {
    "quote": "We can quote this.",
    "refer": "An underwriter should look at this before quoting.",
    "decline": "We would not offer cover.",
    "hold": "We stopped and did not decide.",
}

HOLD_WHY = {
    "ambiguous_company": "More than one company matches this name, and guessing "
                         "which one would be worse than asking.",
    "evidence_unavailable": "A source we needed did not answer. We are not "
                            "treating that silence as good news.",
    "internal_error": "Something broke on our side.",
}


def headline(case: dict) -> str:
    d = case["decision"]
    bits = [VERDICT.get(d["outcome"], d["outcome"])]
    if d["outcome"] == "hold":
        bits.append(HOLD_WHY.get(d.get("hold_reason") or "", ""))
        return " ".join(b for b in bits if b)

    ident = case.get("identity") or {}
    if ident.get("company"):
        bits.append(f"We matched the applicant to "
                    f"{(ident['company'].get('name') or '').rstrip('.')}.")
    else:
        bits.append("We could not work out which company this is, so we checked "
                    "the declaration against similar businesses instead.")

    n_bad = sum(1 for f in case["facts"] if f["status"] in ("contradicts", "undeclared"))
    if n_bad:
        bits.append(f"{n_bad} thing{'s' if n_bad > 1 else ''} in the record "
                    f"{'do' if n_bad > 1 else 'does'} not line up with the form.")
    else:
        bits.append("Nothing in the record contradicts the form.")

    missing = d["gate"]["missing"]
    if missing:
        names = " and ".join(FIELD_NAMES.get(m, m) for m in missing)
        bits.append(f"We cannot put a final price on it until we know {names} — "
                    f"the figure shown is provisional.")
    return " ".join(bits)


def findings(case: dict) -> list[dict[str, str]]:
    """One plain sentence per thing worth knowing, worst first."""
    out: list[dict[str, str]] = []
    facts = case["facts"]

    def src(f):
        """Label for the line, plus the whole source object for the drawer."""
        s = f.get("source") or {}
        where = s.get("what", "")
        when = s.get("dated") or (s.get("fetched") or "")[:10]
        return f"{where}{' · ' + when if when else ''}", s

    for f in facts:
        if f["status"] == "contradicts" and f["field"] == "headcount":
            declared = next((x["value"] for x in facts
                             if x["field"] == "headcount" and x["origin"] == "declared"), "?")
            out.append({"tone": "bad",
                        "text": f"The form says {declared} staff. The record shows "
                                f"{f['value']}. That is more than the tolerance allows, "
                                f"so it is treated as understated.",
                        "source": src(f)[0], "src": src(f)[1]})
        elif f["status"] == "contradicts" and f["field"] == "sites":
            declared = next((x["value"] for x in facts
                             if x["field"] == "sites" and x["origin"] == "declared"), "?")
            out.append({"tone": "bad",
                        "text": f"The form says {declared} premises. We can see {f['value']}.",
                        "source": src(f)[0], "src": src(f)[1]})
        elif f["field"] == "undeclared_site":
            out.append({"tone": "bad",
                        "text": f"There is activity at {f['value']}, which the form "
                                f"does not mention.",
                        "source": src(f)[0], "src": src(f)[1]})
        elif f["field"] == "hiring_location":
            out.append({"tone": "info",
                        "text": f"They are hiring in {f['value']}. That fits within the "
                                f"number of sites declared.",
                        "source": src(f)[0], "src": src(f)[1]})
        elif f["field"] == "hiring_abroad":
            out.append({"tone": "info",
                        "text": f"Open roles abroad ({f['value']}). Group operations "
                                f"outside India are not premises on this policy.",
                        "source": src(f)[0], "src": src(f)[1]})
        elif f["field"] == "staff_abroad":
            out.append({"tone": "info",
                        "text": f"Some staff are recorded in {f['value']}. That is usually "
                                f"a sales or buying office, not premises, so it does not "
                                f"change the price. Worth asking whether stock is held there.",
                        "source": src(f)[0], "src": src(f)[1]})
        elif f["field"] == "undeclared_hazard":
            out.append({"tone": "bad",
                        "text": f"Evidence of {f['value']} on site. The form does not "
                                f"declare it, and it carries a higher fire risk than "
                                f"what was declared.",
                        "source": src(f)[0], "src": src(f)[1]})
        elif f["field"] == "adverse_event" and f["status"] == "matches":
            out.append({"tone": "bad", "text": "A loss event at this company was confirmed.",
                        "source": src(f)[0], "src": src(f)[1]})
        elif f["field"] == "certification" and f["status"] == "matches":
            out.append({"tone": "good",
                        "text": f"They hold {f['value'].replace('_', ' ')}, which earns a "
                                f"discount.", "source": src(f)[0], "src": src(f)[1]})
        elif f["field"] == "class_percentile":
            out.append({"tone": "info",
                        "text": f"For this trade, the declared size is larger than "
                                f"{f['value']}% of comparable businesses, so the "
                                f"declaration is not unusually low.",
                        "source": src(f)[0], "src": src(f)[1]})
        elif f["field"] == "headcount_growth_pct" and isinstance(f["value"], (int, float)) \
                and f["value"] >= 50:
            out.append({"tone": "bad",
                        "text": f"Headcount is up {f['value']}% year on year. Controls "
                                f"usually lag that kind of growth.",
                        "source": src(f)[0], "src": src(f)[1]})
        elif f["field"] == "adverse_event" and f.get("evidence_kind") == "search_negative":
            out.append({"tone": "good",
                        "text": "We searched for fires, accidents and pollution notices "
                                "naming this company and found none. That is not the "
                                "same as not looking.",
                        "source": src(f)[0], "src": src(f)[1]})

    order = {"bad": 0, "info": 1, "good": 2}
    out.sort(key=lambda x: order.get(x["tone"], 3))
    return out


def unchecked(case: dict) -> list[str]:
    seen = set()
    out = []
    for f in case["facts"]:
        if f["status"] == "cannot_verify" and f["field"] not in seen:
            seen.add(f["field"])
            out.append(FIELD_NAMES.get(f["field"], f["field"]))
    for q in case.get("questions", []):
        nm = FIELD_NAMES.get(q["field"], q["field"])
        if nm not in out:
            out.append(nm)
    return out


def price_story(case: dict) -> list[str]:
    """Why the premium is what it is, in words."""
    out = []
    for s in case["decision"]["steps"]:
        m = s["multiplier"]
        if "_BASE_" in s["rule"]:
            out.append(f"Base rate for this occupancy: {s.get('explain','')}")
        elif m > 1:
            out.append(f"+{round((m - 1) * 100)}% — {s.get('explain', s['rule'])}")
        elif m < 1:
            out.append(f"−{round((1 - m) * 100)}% — {s.get('explain', s['rule'])}")
    return out
