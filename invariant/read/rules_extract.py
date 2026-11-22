"""Rule-based fallback reader: broker text -> the same raw dict the fill_form tool returns.

Used when there is no API key and no fixture, or the API call fails. Plain regex and
keywords; the normalizer then does the same canonicalisation as for Claude's output.
It is weaker than the LLM on messy text, and that is acceptable: it keeps the desk running.
"""
from __future__ import annotations

import re
from typing import Optional

from invariant.read.normalize import (
    _GLUE, _HUNDRED, _INDUSTRY_KEYWORDS, _SCALES, _UNITS, KNOWN_CITIES, looks_like_injection,
    normalize_ask,
)

# words that end a company name; the run of them is part of the name
_LEGAL = {"pvt", "private", "ltd", "limited", "llp", "p"}
_NAME_END = _LEGAL | {"co", "company", "works", "exports", "exporters", "industries", "tannery",
                      "tanners", "garments", "mills", "enterprises", "traders", "textiles",
                      "overseas", "international", "udyog", "footwear", "brassware", "fabrics"}
_CAP_STOP = {"a", "an", "the", "our", "my", "client", "need", "needs", "please", "i", "we",
             "insured", "applicant", "proposer"}
_LOWER_STOP = {"hai", "ek", "a", "an", "the", "is", "for", "of", "and", "exporter", "bhai",
               "firm", "called", "named", "naam", "ka", "ki", "ke", "se", "ye", "yeh", "company"}
_PEOPLE = {"employees", "employee", "staff", "workers", "worker", "people", "log", "karamchari",
           "heads", "employes", "persons", "labour", "labourers", "workforce", "manpower"}
_SITES = {"units", "unit", "unitz", "factories", "factory", "plants", "plant", "sites", "site",
          "locations", "branches", "godowns", "facilities", "workshops"}
_COVER_WORDS = re.compile(r"\b(?:cover|insure|insurance|insured|policy|sum insured|si|bima)\b", re.I)
_PRODUCTS = {"leather", "garment", "garments", "shoe", "shoes", "footwear", "textile", "textiles",
             "brass", "brassware", "handicraft", "handicrafts", "rice", "spice", "spices", "yarn",
             "fabric", "fabrics", "carpet", "carpets", "hide", "hides", "apparel"}
_COUNTRIES = ["Germany", "Italy", "France", "Spain", "China", "Bangladesh", "Japan", "Netherlands",
              "Belgium", "Canada", "Australia", "Sri Lanka", "Nepal", "Saudi Arabia", "Vietnam",
              "United States", "United Kingdom", "United Arab Emirates", "Europe", "Poland",
              "Russia", "Brazil", "Mexico", "Turkey", "South Africa", "Singapore", "Malaysia"]
_COUNTRY_CAPS = ["USA", "US", "UK", "UAE", "EU"]  # matched case-sensitively only


# ------------------------------------------------------------------ company


def _words(text: str) -> list[tuple[str, int, int]]:
    return [(m.group(), m.start(), m.end()) for m in re.finditer(r"[A-Za-z][A-Za-z0-9&'/]*\.?", text)]


def _clean(w: str) -> str:
    return w.lower().rstrip(".").replace("'", "")


def _gap_breaks(text: str, a: int, b: int) -> bool:
    """Punctuation between two words ends a name ("," ";" "(" " - ")."""
    return bool(re.search(r"[,;:()\n!?]|\s-\s", text[a:b]))


def _is_cap(w: str) -> bool:
    return w[:1].isupper()


def _company(text: str) -> tuple[Optional[str], Optional[tuple[int, int]]]:
    ws = _words(text)
    cands = []  # (legal?, start_char, end_char)
    i = 0
    while i < len(ws):
        if _clean(ws[i][0]) not in _NAME_END:
            i += 1
            continue
        j = i  # extend the run of suffix words forward
        while j + 1 < len(ws) and _clean(ws[j + 1][0]) in _NAME_END and \
                not _gap_breaks(text, ws[j][2], ws[j + 1][1]):
            if ws[j][0].endswith(".") and _clean(ws[j][0]) not in _LEGAL:
                break  # sentence end: "... Exports. Works ..."
            j += 1
        legal = _clean(ws[j][0]) in _LEGAL
        cap = _is_cap(ws[i][0])
        if cap or legal:
            k = i  # walk back over the name body
            while k - 1 >= 0 and i - k < 5 and not _gap_breaks(text, ws[k - 1][2], ws[k][1]) \
                    and not ws[k - 1][0].endswith("."):
                w = ws[k - 1][0]
                if cap and (not _is_cap(w) or _clean(w) in _CAP_STOP):
                    break
                if not cap and (_clean(w) in _LOWER_STOP or w.lower() in _UNITS):
                    break
                k -= 1
            body = [w for w, _, _ in ws[k:i]]
            if body and any(_clean(w) not in _NAME_END and _clean(w) != "m/s" for w in body):
                cands.append((legal, ws[k][1], ws[j][2]))
        i = j + 1
    if cands:
        legal_first = sorted(cands, key=lambda c: (not c[0], c[1]))[0]
        _, s, e = legal_first
        return text[s:e].rstrip(" ,"), (s, e)
    m = re.search(r"\bM/s\.?\s+((?:[A-Z][\w&'-]*\s*){1,5})", text)
    if m:
        return m.group(1).strip(), m.span(1)
    m = re.match(r"\s*((?:[A-Z][\w&'-]*\s+){1,4}[A-Z][\w&'-]*)\s*(?:,|\b(?:wants|needs|has|is|applying|seeks)\b)",
                 text)
    if m and _clean(m.group(1).split()[0]) not in _CAP_STOP:
        return m.group(1).strip(), m.span(1)
    return None, None


# ------------------------------------------------------------------ numbers near keywords


def _toks(text: str) -> list[str]:
    t = text.lower().replace("₹", " rs ")
    t = re.sub(r"(?<=\d),(?=\d)", "", t)
    t = re.sub(r"(?<=[a-z])-(?=[a-z])", " ", t)
    return re.findall(r"\d+(?:\.\d+)?|[a-z]+|[.,;:()!?\n-]", t)


def _is_num(t: str) -> bool:
    return t[0].isdigit() or t in _UNITS or t in _HUNDRED or t in _SCALES


def _run_before(toks: list[str], i: int) -> Optional[str]:
    """Number phrase ending right before toks[i] (one filler word allowed)."""
    j = i - 1
    if j >= 0 and not _is_num(toks[j]) and toks[j] not in _GLUE and toks[j] not in "-.,;:()!?\n":
        j -= 1  # e.g. "120 permanent employees"
    run = []
    while j >= 0 and (_is_num(toks[j]) or toks[j] in ("and", "about", "around", "approx", "lagbhag")
                      or (toks[j] == "-" and run and j > 0 and _is_num(toks[j - 1]))):
        run.insert(0, toks[j])
        j -= 1
    while run and run[0] in ("and",):
        run.pop(0)
    if len(run) > 1 and run[0] in ("a", "an"):
        run.pop(0)
    if not any(_is_num(t) and t not in _SCALES for t in run):
        return None
    return " ".join(run).replace(" - ", "-")


def _run_after(toks: list[str], i: int) -> Optional[str]:
    j = i + 1
    while j < len(toks) and toks[j] in (":", "of", "is", "-", "rs", "inr"):
        j += 1
    run = []
    while j < len(toks) and (_is_num(toks[j]) or toks[j] in ("rs", "inr")):
        run.append(toks[j])
        j += 1
    return " ".join(run) if any(_is_num(t) and t not in _SCALES for t in run) else None


def _count_near(text: str, nouns: set[str]) -> Optional[str]:
    toks = _toks(text)
    for i, t in enumerate(toks):
        if t in nouns:
            got = _run_before(toks, i)
            if got:
                return got
    for i, t in enumerate(toks):  # "headcount: 120", "employees - 85"
        if t in nouns or t == "headcount":
            got = _run_after(toks, i)
            if got:
                return got
    return None


def _money_phrases(text: str) -> list[tuple[int, str]]:
    """(char position, phrase) for amounts with a scale word or a Rs/₹/INR prefix."""
    out = []
    pat = re.compile(r"(?:(?:rs\.?|₹|inr)\s*)?\d[\d,]*(?:\.\d+)?(?:\s*-\s*\d+(?:\.\d+)?)?\s*"
                     r"(?:crores?|cr|lakhs?|lacs?|l|k|thousand|million|mn)?\b"
                     r"|\b(?:(?:ek|do|teen|char|paanch|dedh|dhai|one|two|three|four|five|ten|das)\s+)"
                     r"(?:crores?|lakhs?)\b", re.I)
    for m in pat.finditer(text):
        s = m.group().strip()
        if re.search(r"crore|cr|lakh|lac|\bl\b|million|mn|rs|₹|inr", s, re.I):
            out.append((m.start(), s))
    return out


def _sum_insured(text: str) -> Optional[str]:
    money = _money_phrases(text)
    covers = [m.start() for m in _COVER_WORDS.finditer(text)]
    if not money or not covers:
        return None
    pos, phrase = min(money, key=lambda p: min(abs(p[0] - c) for c in covers))
    return phrase if min(abs(pos - c) for c in covers) <= 60 else None


def _cover_type(text: str) -> Optional[str]:
    found = set()
    for m in re.finditer(r"\b(fire|wc|w\.c\.|workm[ae]n'?s?\s*comp\w*|employees?'?\s*comp\w*|package)\b",
                         text, re.I):
        window = text[max(0, m.start() - 40): m.end() + 40]
        if _COVER_WORDS.search(window):
            w = m.group(1).lower()
            found.add("fire" if w == "fire" else "fire and wc" if w == "package" else "wc")
    if not found:
        return None
    return "fire and wc" if ("fire" in found and "wc" in found) or "fire and wc" in found else found.pop()


# ------------------------------------------------------------------ the rest


def _city(text: str, company_span) -> Optional[str]:
    t = text if not company_span else text[:company_span[0]] + " " + text[company_span[1]:]
    hits = []
    for c in KNOWN_CITIES:
        m = re.search(rf"\b{re.escape(c)}\b", t, re.I)
        if m:
            hits.append((m.start(), c))
    return min(hits)[1] if hits else None


def _industry(text: str) -> Optional[str]:
    t = text.lower()
    for occ, words in _INDUSTRY_KEYWORDS:
        if any(re.search(rf"\b{re.escape(w)}", t) for w in words):
            return occ
    return None


def _activities(text: str) -> list[str]:
    t = text.lower()
    out = []
    for m in re.finditer(r"\b([a-z]+)\s+export(?:er|ers|s|ing)?\b", t):
        if m.group(1) in _PRODUCTS:
            out.append(f"{m.group(1)} export")
    for m in re.finditer(r"\bexport(?:ing|s)?\s+(?:of\s+)?([a-z]+)", t):
        if m.group(1) in _PRODUCTS:
            out.append(f"{m.group(1)} export")
    for m in re.finditer(r"\b([a-z]+)\s+(stitching|tanning|dyeing|manufacturing)\b", t):
        if m.group(1) in _PRODUCTS:
            out.append(f"{m.group(1)} {m.group(2)}")
    return out


def _countries(text: str) -> list[str]:
    out = [c for c in _COUNTRIES if re.search(rf"\b{re.escape(c)}\b", text, re.I)]
    out += [c for c in _COUNTRY_CAPS if re.search(rf"\b{c}\b", text)]
    return out


def rules_extract(text: str) -> dict:
    """Same keys as the fill_form tool input, values as raw strings for the normalizer."""
    company, span = _company(text)
    rest = text if not span else text[:span[0]] + " " + text[span[1]:]
    dom = re.search(r"\b([a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|in|co\.in|net|org|example))\b", text, re.I)
    return {
        "company_name": company,
        "trade_names": [],
        "domain": dom.group(1) if dom else None,
        "city": _city(text, span),
        "state": None,
        "industry": _industry(rest),
        "declared_headcount": _count_near(rest, _PEOPLE),
        "declared_sites": _count_near(rest, _SITES),
        "countries": _countries(rest),
        "activities": _activities(rest),
        "cover_type": _cover_type(rest),
        "sum_insured_inr": _sum_insured(rest),
        "ask": normalize_ask(text),
        "injection_attempt": looks_like_injection(text),
    }
