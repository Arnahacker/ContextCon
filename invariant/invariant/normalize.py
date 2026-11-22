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

# industry words -> the occupancy key in rules.yaml. ORDER MATTERS: the first
# match wins, so the more hazardous process is listed first ("leather tannery"
# must not fall through to leather goods).
OCCUPANCY = [
    (("chemical", "dyeing", "dye house", "dyes", "electroplat", "solvent", "paint manufact",
      "pigment", "fertiliser", "fertilizer", "pesticide", "agrochemical"), "chemical_processing"),
    (("foundry", "forging", "forge", "casting", "steel melt", "smelt"), "foundry_forging"),
    (("tanner", "tanning", "tannery", "chrome", "leather manufact"), "leather_tanning"),
    (("plastic", "rubber", "polymer", "tyre", "foam"), "plastics_rubber"),
    (("spinning", "weaving", "textile mill", "yarn", "cotton mill", "knitting", "textile"),
     "textile_mill"),
    (("furniture", "timber", "sawmill", "plywood"), "furniture_wood"),
    (("cold storage", "cold chain", "refrigerated"), "cold_storage"),
    (("printing", "paper", "packaging", "carton", "corrugat"), "printing_paper"),
    (("garment", "stitching", "apparel", "tailoring", "sewing", "hosiery"), "garment_stitching"),
    (("pharma", "drug", "formulation"), "pharmaceutical"),
    (("food", "bakery", "dairy", "snack", "spice", "rice mill", "flour", "beverage",
      "confectioner"), "food_processing"),
    (("warehouse", "godown", "storage", "logistics"), "warehouse"),
    (("engineering", "machining", "fabrication", "auto component", "auto parts",
      "cnc", "machine shop", "sheet metal"), "engineering_workshop"),
    (("electronic", "pcb"), "electronics_assembly"),
    (("leather", "footwear", "shoe", "handicraft", "toy", "manufactur"), "light_manufacturing"),
    (("hotel", "restaurant", "resort", "catering"), "hotel_restaurant"),
    (("hospital", "clinic", "diagnostic", "nursing home"), "hospital_clinic"),
    (("retail", "showroom", "jewel"), "retail_shop"),
    (("office", "software", "it services", "consult", "bpo", "call centre"), "office"),
]


def cover_key(text: str) -> str:
    """Any way of naming a line of cover -> the key in rules.yaml covers."""
    t = (text or "").strip().lower()
    if any(w in t for w in ("workmen", "wc", "employee comp", "employees comp",
                            "employees' comp", "ec policy")):
        return "wc"
    if any(w in t for w in ("burglary", "theft", "housebreaking")):
        return "burglary"
    if any(w in t for w in ("marine", "cargo", "transit", "shipment")):
        return "marine_cargo"
    return "fire"


def clean_domain(d: Optional[str]) -> Optional[str]:
    """'https://www.Rajda.in/about' -> 'rajda.in'."""
    if not d:
        return None
    d = str(d).strip().lower()
    d = re.sub(r"^[a-z]+://", "", d).split("/")[0].split("?")[0]
    d = re.sub(r"^www\.", "", d).strip(".")
    return d if re.fullmatch(r"[a-z0-9-]+(\.[a-z0-9-]+)+", d) else None


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


def _occ_rank(key: str) -> int:
    for i, (_, k) in enumerate(OCCUPANCY):
        if k == key:
            return i
    return len(OCCUPANCY)


def to_occupancy(industry: Optional[str], activities: list[str] | None = None) -> str:
    """The most hazardous occupancy among the things declared, each matched ON
    ITS OWN. Joining them into one string made "leather" + "manufacturing"
    read as "leather manufact" (a tannery) - wording, not the business."""
    best = "unknown"
    for text in [industry or ""] + list(activities or []):
        t = (text or "").lower()
        for needles, key in OCCUPANCY:
            if any(n in t for n in needles):
                if _occ_rank(key) < _occ_rank(best):
                    best = key
                break
    return best


# canonical trade words. A model says "leather exporter", "leather goods
# export business", "tanning unit"; the evidence query must see ONE word, or
# the wording reaches the cohort search and the hash. First match wins, so the
# more specific trade comes first.
TRADES = [
    (("tanner", "tanning", "tannery"), "tannery"),
    (("footwear", "shoe"), "footwear"),
    (("leather",), "leather"),
    (("garment", "stitching", "apparel", "hosiery"), "garment stitching"),
    (("spinning", "weaving", "yarn", "textile"), "textile"),
    (("dyeing", "dye house"), "dyeing"),
    (("pharma",), "pharmaceutical"),
    (("chemical", "pigment"), "chemical"),
    (("foundry",), "foundry"), (("forging",), "forging"),
    (("plastic",), "plastics"), (("rubber", "tyre"), "rubber"),
    (("furniture", "timber", "plywood"), "furniture"),
    (("cold storage", "cold chain"), "cold storage"),
    (("warehouse", "godown"), "warehouse"), (("logistics",), "logistics"),
    (("dairy",), "dairy"), (("bakery",), "bakery"), (("food",), "food processing"),
    (("printing",), "printing"), (("packaging",), "packaging"),
    (("auto component", "auto parts"), "auto components"),
    (("engineering", "machining", "fabrication"), "engineering"),
    (("electronic",), "electronics"), (("hotel",), "hotel"), (("restaurant",), "restaurant"),
    (("hospital", "clinic"), "hospital"), (("software", "it services"), "software"),
    (("retail", "showroom"), "retail"),
]


def canonical_industry(text: Optional[str]) -> Optional[str]:
    t = (text or "").strip().lower()
    if not t:
        return None
    for needles, label in TRADES:
        if any(n in t for n in needles):
            return label
    return t


def canonical_activity(text: str) -> str:
    t = (text or "").strip().lower()
    if "export" in t:
        return "export"
    if "import" in t:
        return "import"
    return canonical_industry(t) or t


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
    form.activities = sorted({canonical_activity(a) for a in (form.activities or [])
                              if a and str(a).strip()})
    form.trade_names = sorted({t.strip() for t in (form.trade_names or []) if t})
    if form.industry:
        form.industry = canonical_industry(form.industry)
    if form.cover_type:
        form.cover_type = cover_key(form.cover_type)
    for fld in ("annual_wages_inr", "annual_shipments_inr"):
        v = getattr(form, fld)
        if v is not None and not isinstance(v, int):
            setattr(form, fld, money_to_int(v))
    form.domain = clean_domain(form.domain)
    if form.gstin:
        form.gstin = re.sub(r"[\s-]", "", str(form.gstin)).upper() or None
    return form
