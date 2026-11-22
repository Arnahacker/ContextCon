"""Turn whatever the model extracted into canonical values.

This is where invariance is actually won. Two wordings must collapse to the
same Form here, or the hashes will not match downstream.
"""
from __future__ import annotations
import re
from typing import Optional

from .schemas import Form

WORDS = {"zero":0,"one":1,"two":2,"three":3,"four":4,"five":5,"six":6,"seven":7,
         "eight":8,"nine":9,"ten":10,"eleven":11,"twelve":12,"fifteen":15,
         "twenty":20,"thirty":30,"forty":40,"fifty":50,"sixty":60,"seventy":70,
         "eighty":80,"ninety":90,"hundred":100,"thousand":1000,"lakh":100000,
         "lac":100000,"crore":10000000,
         # Hinglish is how half of Indian broking actually talks
         "ek":1,"do":2,"teen":3,"tin":3,"char":4,"chaar":4,"paanch":5,"panch":5,
         "chhe":6,"chey":6,"saat":7,"aath":8,"nau":9,"das":10,"bees":20,
         "sau":100,"hazaar":1000,"hajaar":1000}

# industry words -> the occupancy key in rules.yaml
OCCUPANCY = [
    (("tanner", "tanning", "tannery", "chrome", "leather manufact"), "leather_tanning"),
    (("chemical", "dyeing", "dye house", "electroplat"), "chemical_processing"),
    (("garment", "stitching", "apparel", "tailoring", "sewing"), "garment_stitching"),
    (("warehouse", "godown", "storage", "logistics"), "warehouse"),
    (("leather", "footwear", "shoe"), "light_manufacturing"),
    (("office", "software", "it services", "consult"), "office"),
]


def words_to_int(text: str) -> Optional[int]:
    """'one hundred twenty' -> 120. Returns None if it is not a number in words."""
    toks = re.findall(r"[a-z]+", text.lower())
    toks = [t for t in toks if t in WORDS or t == "and"]
    if not toks or not any(t in WORDS for t in toks):
        return None
    total, current = 0, 0
    for t in toks:
        if t == "and":
            continue
        v = WORDS[t]
        if v in (100,):
            current = (current or 1) * v
        elif v in (1000, 100000, 10000000):
            total += (current or 1) * v
            current = 0
        else:
            current += v
    return (total + current) or None


def money_to_int(text: str) -> Optional[int]:
    """'4.5 cr' -> 45000000 ; 'Rs 50 lakh' -> 5000000 ; '50,00,000' -> 5000000."""
    if text is None:
        return None
    s = str(text).lower().replace(",", "").replace("₹", " ").replace("rs.", " ").replace("rs", " ")
    m = re.search(r"(\d+(?:\.\d+)?)\s*(cr|crore|crores|lakh|lakhs|lac|lacs|k|thousand)?", s)
    if not m:
        return words_to_int(s)
    n = float(m.group(1))
    unit = (m.group(2) or "").strip()
    mult = {"cr":1e7,"crore":1e7,"crores":1e7,"lakh":1e5,"lakhs":1e5,"lac":1e5,
            "lacs":1e5,"k":1e3,"thousand":1e3}.get(unit, 1)
    return int(round(n * mult))


def count_to_int(text) -> Optional[int]:
    if text is None:
        return None
    if isinstance(text, int):
        return text
    s = str(text).replace(",", "")
    m = re.search(r"\d+", s)
    if m:
        return int(m.group())
    return words_to_int(s)


def to_occupancy(industry: Optional[str], activities: list[str] | None = None) -> str:
    blob = " ".join([industry or ""] + list(activities or [])).lower()
    for needles, key in OCCUPANCY:
        if any(n in blob for n in needles):
            return key
    return "unknown"


def canonical_name(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    s = name.strip().lower()
    for suffix in (" private limited", " pvt ltd", " pvt. ltd.", " pvt limited",
                   " limited", " ltd.", " ltd", " llp", " & co", " and co", " inc"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip() or None


def normalize(form: Form) -> Form:
    """Canonicalise in place and return. Pure: no network, no clock."""
    form.declared_headcount = count_to_int(form.declared_headcount)
    form.declared_sites = count_to_int(form.declared_sites)
    form.sum_insured_inr = money_to_int(form.sum_insured_inr) if form.sum_insured_inr else None
    form.countries = sorted({(c or "").strip().upper()[:2] for c in (form.countries or []) if c})
    form.activities = sorted({a.strip().lower() for a in (form.activities or []) if a})
    form.trade_names = sorted({t.strip() for t in (form.trade_names or []) if t})
    if form.industry:
        form.industry = form.industry.strip().lower()
    if form.cover_type:
        ct = form.cover_type.strip().lower()
        form.cover_type = "wc" if ct in ("wc", "workmen", "workmens compensation",
                                         "workmen's compensation", "employee comp") else "fire"
    return form
