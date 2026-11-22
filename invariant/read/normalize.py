"""Deterministic normalizer: different wordings of the same fact converge here.

The LLM copies values as stated ("ek sau bees", "3 crore", "three units");
this module turns them into the canonical Form values. No network, no LLM.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from invariant.shapes import Form

# ------------------------------------------------------------------ numbers

_UNITS = {
    # english
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
    "thirty": 30, "forty": 40, "fourty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80,
    "ninety": 90, "single": 1, "a": 1, "an": 1, "dozen": 12, "half": 0.5,
    # hindi / hinglish
    "ek": 1, "do": 2, "teen": 3, "tin": 3, "char": 4, "chaar": 4, "paanch": 5, "panch": 5,
    "chhe": 6, "chhah": 6, "chah": 6, "che": 6, "saat": 7, "sat": 7, "aath": 8, "aat": 8,
    "nau": 9, "das": 10, "gyarah": 11, "barah": 12, "baarah": 12, "terah": 13, "chaudah": 14,
    "pandrah": 15, "solah": 16, "satrah": 17, "atharah": 18, "unnis": 19, "bees": 20, "bis": 20,
    "pachees": 25, "pachis": 25, "tees": 30, "chalis": 40, "chaalis": 40, "pachas": 50,
    "pachaas": 50, "saath": 60, "sattar": 70, "assi": 80, "nabbe": 90, "dedh": 1.5, "dhai": 2.5,
    "adha": 0.5, "aadha": 0.5,
}
_HUNDRED = {"hundred", "sau", "so"}
_SCALES = {
    "thousand": 1_000, "hazaar": 1_000, "hazar": 1_000, "hajar": 1_000, "k": 1_000,
    "lakh": 100_000, "lakhs": 100_000, "lac": 100_000, "lacs": 100_000, "l": 100_000,
    "million": 1_000_000, "mn": 1_000_000, "m": 1_000_000,
    "crore": 10_000_000, "crores": 10_000_000, "cr": 10_000_000, "karod": 10_000_000,
    "karor": 10_000_000, "billion": 1_000_000_000, "bn": 1_000_000_000,
}
# words that may sit inside a number phrase without breaking it
_GLUE = {"and", "rs", "inr", "rupees", "rupee", "about", "around", "approx", "approximately",
         "roughly", "nearly", "almost", "lagbhag", "karib", "kareeb", "only", "sq", "ft", "sqft",
         "square", "feet", "foot", "of", "+", "plus"}
_RANGE_SEP = re.compile(r"\s*(?:(?<=\d)-(?=\d)|\s-\s|–|—|\bto\b|\bse\b|\bor\b)\s*", re.I)


def _tokens(text: str) -> list[str]:
    t = text.lower().replace("₹", " rs ").replace("rs.", "rs ")
    t = re.sub(r"(?<=\d),(?=\d)", "", t)  # 1,20,000 -> 120000 (any grouping)
    t = re.sub(r"(?<=[a-z])-(?=[a-z])", " ", t)  # twenty-five
    return re.findall(r"\d+(?:\.\d+)?|[a-z]+|\+", t)


def _parse_single(text: str) -> tuple[Optional[float], bool]:
    """(value, has_scale). None when no number or when two separate numbers appear."""
    total = 0.0
    current: Optional[float] = None
    seen = False
    gap = False  # a non-number word appeared after a number
    has_scale = False
    for tok in _tokens(text):
        if re.fullmatch(r"\d+(?:\.\d+)?", tok) or tok in _UNITS:
            if tok in ("a", "an") and seen:
                continue
            v = float(tok) if tok[0].isdigit() else _UNITS[tok]
            if gap:
                return None, False
            current = (current or 0) + v
            seen = True
        elif tok in _HUNDRED and seen:
            current = (current or 1) * 100
        elif tok in _SCALES and seen:
            total += (current if current is not None else 1) * _SCALES[tok]
            current = None
            has_scale = True
        elif tok in _GLUE:
            continue
        elif seen:
            gap = True
    if not seen:
        return None, False
    return total + (current or 0), has_scale


def parse_range(text: Any) -> Optional[tuple[float, float]]:
    """'15-20 thousand' -> (15000, 20000); '4 se 5 crore' -> (4e7, 5e7). None if not a range."""
    if text is None or isinstance(text, (int, float)):
        return None
    parts = _RANGE_SEP.split(str(text), maxsplit=1)
    if len(parts) != 2:
        return None
    lo, lo_scaled = _parse_single(parts[0])
    hi, hi_scaled = _parse_single(parts[1])
    if lo is None or hi is None:
        return None
    if not lo_scaled and hi_scaled:  # share the trailing scale: "15-20 thousand"
        scale = _trailing_scale(parts[1])
        lo *= scale
    lo, hi = sorted((lo, hi))
    return lo, hi


def _trailing_scale(text: str) -> float:
    for tok in reversed(_tokens(text)):
        if tok in _SCALES:
            return _SCALES[tok]
    return 1


def parse_number(text: Any) -> Optional[float]:
    """A single number from digits, Indian grouping, lakh/crore, English or Hindi words.
    Ranges return their midpoint."""
    if text is None or isinstance(text, bool):
        return None
    if isinstance(text, (int, float)):
        return float(text)
    rng = parse_range(text)
    if rng:
        return (rng[0] + rng[1]) / 2
    return _parse_single(str(text))[0]


def parse_int(text: Any) -> Optional[int]:
    v = parse_number(text)
    return None if v is None else int(round(v))


def indian_format(n: float) -> str:
    """12345678 -> '1,23,45,678' (lakh/crore grouping)."""
    n = int(round(n))
    sign, s = ("-" if n < 0 else ""), str(abs(n))
    if len(s) <= 3:
        return sign + s
    head, tail = s[:-3], s[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return sign + ",".join(groups + [tail])


def short_inr(n: float) -> str:
    """45000000 -> '4.5 Cr'; 500000 -> '5 L'."""
    for div, unit in ((10_000_000, "Cr"), (100_000, "L")):
        if abs(n) >= div:
            return f"{n / div:g} {unit}"
    return indian_format(n)


# ------------------------------------------------------------------ vocabularies

OCCUPANCIES = ["leather", "footwear", "garments", "textiles", "food_processing", "engineering",
               "chemicals", "brassware", "other"]
# order matters: first hit wins ("leather shoes" is footwear)
_INDUSTRY_KEYWORDS = [
    ("footwear", ["footwear", "shoe", "sandal", "chappal", "slipper", "boot"]),
    ("leather", ["leather", "tanner", "tannery", "tanning", "hide", "chamda"]),
    ("garments", ["garment", "apparel", "stitching", "clothing", "readymade", "hosiery", "kapde"]),
    ("textiles", ["textile", "spinning", "weaving", "yarn", "fabric", "handloom", "dyeing", "mill"]),
    ("food_processing", ["food", "rice", "flour", "spice", "dairy", "snack", "bakery", "agro"]),
    ("brassware", ["brass", "handicraft", "metalware"]),
    ("chemicals", ["chemical", "pharma", "paint", "fertiliser", "fertilizer", "solvent"]),
    ("engineering", ["engineering", "machining", "fabrication", "forging", "casting", "auto part",
                     "machinery", "tools"]),
]


def normalize_industry(text: Optional[str]) -> Optional[str]:
    if not text or not str(text).strip():
        return None
    t = str(text).lower().replace("_", " ")
    if t.strip() in OCCUPANCIES:
        return t.strip()
    for occ, words in _INDUSTRY_KEYWORDS:
        if any(w in t for w in words):
            return occ
    return "other"


def _industry_from_name(name: Optional[str]) -> Optional[str]:
    occ = normalize_industry(name)
    return None if occ in (None, "other") else occ


def normalize_cover_type(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    t = str(text).lower()
    fire = "fire" in t or "aag" in t
    wc = bool(re.search(r"\bwc\b|workm[ae]n|worker|employee.?s?.? comp|compensation", t))
    both = bool(re.search(r"\bboth\b|fire.?wc|fire_wc", t))
    if both or (fire and wc):
        return "fire_wc"
    if wc:
        return "wc"
    if fire:
        return "fire"
    return None


# ------------------------------------------------------------------ names and places

_SUFFIXES = [  # (pattern at end of name, canonical)
    (r"(?:private|pvt\.?|pvt)\s*\.?\s*(?:limited|ltd\.?)", "Pvt Ltd"),
    (r"p\.?\s*ltd\.?", "Pvt Ltd"),
    (r"(?:limited|ltd\.?)", "Ltd"),
    (r"(?:company|co\.?)", "Co"),
    (r"(?:llp)", "LLP"),
]


def _title(s: str) -> str:
    return " ".join(w[:1].upper() + w[1:].lower() for w in s.split())


def normalize_company(name: Optional[str]) -> Optional[str]:
    if not name or not str(name).strip():
        return None
    s = re.sub(r"\s+", " ", str(name)).strip().strip(".,;:-")
    s = re.sub(r"^(?:m/s\.?|messrs\.?)\s*", "", s, flags=re.I)
    suffix = ""
    for pat, canon in _SUFFIXES:
        m = re.search(r"[\s,]+" + pat + r"\s*$", s, flags=re.I)
        if m:
            s, suffix = s[: m.start()], canon
            break
    s = _title(s.strip(" ,."))
    return f"{s} {suffix}".strip() or None


_CITY_ALIASES = {"bombay": "Mumbai", "madras": "Chennai", "calcutta": "Kolkata",
                 "bangalore": "Bengaluru", "cawnpore": "Kanpur", "new delhi": "Delhi"}
# known cities, used only to infer city from a company name when the text gives none
KNOWN_CITIES = ["Kanpur", "Agra", "Tiruppur", "Ranipet", "Vellore", "Moradabad", "Jaipur",
                "Surat", "Chennai", "Mumbai", "Delhi", "Kolkata", "Ludhiana", "Unnao", "Noida",
                "Ahmedabad", "Pune", "Bengaluru", "Hyderabad", "Coimbatore", "Jalandhar"]
_STATE_ALIASES = {"up": "Uttar Pradesh", "tn": "Tamil Nadu", "mh": "Maharashtra",
                  "gj": "Gujarat", "rj": "Rajasthan", "pb": "Punjab", "wb": "West Bengal",
                  "ka": "Karnataka", "dl": "Delhi"}


def normalize_city(city: Optional[str]) -> Optional[str]:
    if not city or not str(city).strip():
        return None
    c = re.sub(r"\s+", " ", str(city)).strip(" ,.").split(",")[0].strip()
    return _CITY_ALIASES.get(c.lower(), _title(c)) or None


def normalize_state(state: Optional[str]) -> Optional[str]:
    if not state or not str(state).strip():
        return None
    s = re.sub(r"\s+", " ", str(state)).strip(" ,.")
    return _STATE_ALIASES.get(s.lower(), _title(s))


def _city_from_name(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    first = name.split()[0]
    return first if first in KNOWN_CITIES else None


def normalize_domain(d: Optional[str]) -> Optional[str]:
    if not d or not str(d).strip():
        return None
    d = re.sub(r"^[a-z]+://", "", str(d).strip().lower())
    d = re.sub(r"^www\.", "", d).split("/")[0]
    return d or None


_COUNTRY_ALIASES = {"usa": "United States", "us": "United States", "u.s.": "United States",
                    "america": "United States", "united states of america": "United States",
                    "uk": "United Kingdom", "britain": "United Kingdom", "england": "United Kingdom",
                    "uae": "United Arab Emirates", "dubai": "United Arab Emirates",
                    "europe": "Europe", "eu": "Europe"}


def normalize_countries(items: Any) -> list[str]:
    out = set()
    for c in _as_list(items):
        c = re.sub(r"\s+", " ", c).strip(" ,.")
        if c:
            out.add(_COUNTRY_ALIASES.get(c.lower(), _title(c)))
    return sorted(out)


# activities -> short lowercase phrases
_SINGULAR = {"garments": "garment", "shoes": "shoe", "hides": "hide", "goods": "goods",
             "exports": "export", "products": "product", "textiles": "textile"}


def normalize_activity(a: str) -> Optional[str]:
    t = re.sub(r"[^a-z ]", " ", a.lower())
    t = re.sub(r"\b(?:the|a|an|we|only|do|just|of|and)\b", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    if not t:
        return None
    t = re.sub(r"\bexport(?:er|ers|ing|s)\b", "export", t)
    t = " ".join(_SINGULAR.get(w, w) for w in t.split())
    m = re.fullmatch(r"(export|stitching|tanning|manufacturing|dyeing) (.+)", t)
    if m:  # "export leather" / "stitching garment" -> "leather export" / "garment stitching"
        t = f"{m.group(2)} {m.group(1)}"
    t = re.sub(r"\bmanufacturer\b", "manufacturing", t)
    return t


def normalize_activities(items: Any) -> list[str]:
    return sorted({x for x in (normalize_activity(a) for a in _as_list(items)) if x})


def normalize_trade_names(items: Any, company: Optional[str]) -> list[str]:
    names = {normalize_company(n) for n in _as_list(items)}
    return sorted(n for n in names if n and n != company)


def normalize_ask(text: Optional[str]) -> Optional[str]:
    """Free-text ask -> 'verify' | 'quote' | 'other'. Wording never reaches the Form."""
    if not text or not str(text).strip():
        return None
    t = str(text).lower()
    if re.search(r"check|verify|match|compare|validate|confirm|jaanch|jaanch|mismatch|what.?s off", t):
        return "verify"
    if re.search(r"cover|quote|insur|premium|policy|bima", t):
        return "quote"
    return "other"


def _as_list(items: Any) -> list[str]:
    if items is None:
        return []
    if isinstance(items, str):
        items = re.split(r"[,;/]| and ", items)
    return [str(x) for x in items if x is not None and str(x).strip()]


# ------------------------------------------------------------------ injection backstop

INJECTION = re.compile(
    r"ignore (?:all |your |the |any |previous |prior |above )*(?:instructions|rules|prompt|guidelines)"
    r"|disregard (?:your |the |all )*(?:instructions|rules)|system prompt|you are now"
    r"|(?:quote|give|approve)(?: me)? (?:the )?(?:lowest|cheapest|minimum) (?:band|premium|rate)"
    r"|override (?:the )?(?:rules|decision)|act as (?:an? )?(?:admin|underwriter)",
    re.I,
)


def looks_like_injection(text: Optional[str]) -> bool:
    return bool(text and INJECTION.search(text))


# ------------------------------------------------------------------ the form


def normalize_form(raw: dict, text: Optional[str] = None) -> Form:
    """Raw tool input (as the LLM wrote it) -> canonical Form."""
    company = normalize_company(raw.get("company_name"))
    industry = normalize_industry(raw.get("industry")) or _industry_from_name(company)
    city = normalize_city(raw.get("city")) or _city_from_name(company)
    return Form(
        company_name=company,
        trade_names=normalize_trade_names(raw.get("trade_names"), company),
        domain=normalize_domain(raw.get("domain")),
        city=city,
        state=normalize_state(raw.get("state")),
        industry=industry,
        declared_headcount=parse_int(raw.get("declared_headcount")),
        declared_sites=parse_int(raw.get("declared_sites")),
        countries=normalize_countries(raw.get("countries")),
        activities=normalize_activities(raw.get("activities")),
        cover_type=normalize_cover_type(raw.get("cover_type")),
        sum_insured_inr=parse_int(raw.get("sum_insured_inr")),
        ask=normalize_ask(raw.get("ask")),
        injection_attempt=bool(raw.get("injection_attempt")) or looks_like_injection(text),
    )
