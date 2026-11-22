"""ILLUSTRATIVE industry norms -- placeholder values to tune, not sourced figures.

Shown on screen labelled as illustrative, like the rate card."""
from __future__ import annotations

LABEL = "illustrative norms (placeholder, not sourced)"

# weeks of stock held, (low, high)
STOCK_WEEKS = {
    "leather": (6, 10), "footwear": (6, 10), "garments": (4, 8), "textiles": (4, 8),
    "food_processing": (2, 4), "engineering": (4, 8), "chemicals": (3, 6), "brassware": (6, 10),
    "retail": (4, 8), "warehousing": (4, 8), "office": (1, 2), "other": (4, 8),
}

# machinery capital per worker, INR lakh, (low, high)
MACHINERY_LAKH_PER_WORKER = {
    "leather": (3, 6), "footwear": (3, 6), "garments": (1, 3), "textiles": (2, 4),
    "food_processing": (4, 8), "engineering": (5, 10), "chemicals": (8, 15), "brassware": (2, 4),
    "retail": (1, 3), "warehousing": (2, 5), "office": (1, 2), "other": (2, 5),
}

# annual sales per worker, INR lakh, (low, high): estimates monthly sales (and so stock)
# when the applicant cannot say and the record has no usable revenue
REVENUE_LAKH_PER_WORKER = {
    "leather": (15, 30), "footwear": (15, 30), "garments": (8, 15), "textiles": (15, 30),
    "food_processing": (20, 40), "engineering": (20, 40), "chemicals": (40, 80), "brassware": (10, 20),
    "retail": (20, 60), "warehousing": (10, 25), "office": (15, 40), "other": (10, 30),
}

# built-up area per worker, sq ft, (low, high): estimates the building when the area is not known
SQFT_PER_WORKER = (60, 150)

# workers per site, (low, high): last-resort headcount when neither applicant nor record has one
HEADCOUNT_PER_SITE = (20, 200)

# a record revenue band wider than this ratio (Crustdata gives e.g. $1B-$1T) is too coarse to use
MAX_REVENUE_RATIO = 5

# construction cost per sq ft by roof type, INR
COST_PER_SQFT = {"concrete": 1800, "tin_sheet": 1150, "other": 800}

# monthly wage per worker used when the wage bill is unknown, INR (low, mid, high)
MONTHLY_WAGE = (12000, 15000, 18000)

WEEKS_PER_MONTH = 4.3
PF_RATE = 0.12
LAKH = 100_000


def stock_weeks(occ: str | None) -> tuple[int, int]:
    return STOCK_WEEKS.get(occ or "other", STOCK_WEEKS["other"])


def revenue_per_worker(occ: str | None) -> tuple[int, int]:
    lo, hi = REVENUE_LAKH_PER_WORKER.get(occ or "other", REVENUE_LAKH_PER_WORKER["other"])
    return lo * LAKH, hi * LAKH


def machinery_per_worker(occ: str | None) -> tuple[int, int]:
    lo, hi = MACHINERY_LAKH_PER_WORKER.get(occ or "other", MACHINERY_LAKH_PER_WORKER["other"])
    return lo * LAKH, hi * LAKH
