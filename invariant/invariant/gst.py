"""What a GSTIN says about itself. Pure: no network.

A GSTIN is 15 characters: 2-digit state code, the 10-character PAN, an entity
number, 'Z', and a check digit. Crustdata cannot look one up, so we check only
what the number itself proves:

  - the check digit       -> a typo or an invented number fails it
  - the PAN's 4th letter  -> the legal form (C company, F firm/LLP, P person...)
  - the state code        -> where this registration is

We never claim the GSTIN belongs to the company. That needs the GST portal.
"""
from __future__ import annotations
import re
from typing import Optional

GSTIN_RE = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

STATES = {
    "01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab",
    "04": "Chandigarh", "05": "Uttarakhand", "06": "Haryana", "07": "Delhi",
    "08": "Rajasthan", "09": "Uttar Pradesh", "10": "Bihar", "11": "Sikkim",
    "12": "Arunachal Pradesh", "13": "Nagaland", "14": "Manipur", "15": "Mizoram",
    "16": "Tripura", "17": "Meghalaya", "18": "Assam", "19": "West Bengal",
    "20": "Jharkhand", "21": "Odisha", "22": "Chhattisgarh", "23": "Madhya Pradesh",
    "24": "Gujarat", "26": "Dadra and Nagar Haveli and Daman and Diu",
    "27": "Maharashtra", "29": "Karnataka", "30": "Goa", "31": "Lakshadweep",
    "32": "Kerala", "33": "Tamil Nadu", "34": "Puducherry",
    "35": "Andaman and Nicobar Islands", "36": "Telangana", "37": "Andhra Pradesh",
    "38": "Ladakh", "97": "Other Territory",
}

PAN_TYPES = {
    "C": "company", "F": "firm or LLP", "P": "individual or proprietorship",
    "H": "Hindu undivided family", "A": "association of persons", "T": "trust",
    "B": "body of individuals", "L": "local authority", "J": "artificial juridical person",
    "G": "government",
}

# what a name suffix says the legal form is
_NAME_FORM = [(re.compile(r"\b(pvt\.?\s*ltd|private\s+limited|limited|ltd)\b\.?", re.I), "C"),
              (re.compile(r"\bllp\b", re.I), "F")]


def clean(g: Optional[str]) -> Optional[str]:
    if not g:
        return None
    g = re.sub(r"[\s-]", "", str(g)).upper()
    return g or None


def check_digit(first14: str) -> str:
    total = 0
    for i, ch in enumerate(first14):
        v = _CHARS.index(ch) * (2 if i % 2 else 1)
        total += v // 36 + v % 36
    return _CHARS[(36 - total % 36) % 36]


def parse(g: Optional[str]) -> Optional[dict]:
    """None if it is not even shaped like a GSTIN."""
    g = clean(g)
    if not g or not GSTIN_RE.match(g):
        return None
    return {"gstin": g, "state_code": g[:2], "state": STATES.get(g[:2]),
            "pan": g[2:12], "pan_type": g[5], "legal_form": PAN_TYPES.get(g[5]),
            "valid_check_digit": check_digit(g[:14]) == g[14]}


def name_form(name: Optional[str]) -> Optional[str]:
    """'C' if the name says it is a company, 'F' for LLP, else None (unknown)."""
    for pat, code in _NAME_FORM:
        if name and pat.search(name):
            return code
    return None
