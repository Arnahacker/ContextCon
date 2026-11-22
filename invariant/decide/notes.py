"""Plain-English reasons behind every number in the price. Pure data, no logic.

The RATES are illustrative placeholders (rate_card.LABEL says so). What is real is the
METHOD they plug into, and these notes say which is which:
  - fire / property in India is rated per mille (per Rs 1,000) of the sum insured, on the
    Standard Fire & Special Perils policy; STFI (storm, tempest, flood, inundation) is the
    usual add-on;
  - workmen's compensation covers liability under the Employees' Compensation Act, 1923,
    and is rated as a percentage of the wage bill;
  - marine cargo is insured at invoice (CIF) value + 10%, rated as a % of that value;
  - GST on general insurance premiums is 18%.
"""

METHOD = ("Premium = the amount we insure x the base rate for this trade, then each named loading "
          "multiplies it, then the minimum premium and 18% GST apply.")

STANDARDS = [
    "Fire is rated per mille (per ₹1,000) of the sum insured, the standard basis for property "
    "under India's Standard Fire & Special Perils policy.",
    "STFI (storm, tempest, flood, inundation) is the usual add-on to fire cover in India, priced on the same sum insured.",
    "Workmen's compensation covers liability under the Employees' Compensation Act, 1923, rated as a % of yearly wages.",
    "Marine cargo is insured at invoice (CIF) value + 10%, the market convention.",
    "GST on general insurance premiums in India is 18%.",
]

ILLUSTRATIVE = ("The rates themselves are placeholders for this demo, not an insurer's filed rates. Their "
                "order follows fire and injury hazard by trade; a real desk would load its own rate card.")

FIRE_WHY = {
    "leather": "Tanning and finishing use chemicals, solvents and boilers, and stored hides burn readily: "
               "one of the higher fire loads in light industry.",
    "footwear": "Leather, rubber and adhesives are in stock, but the work is mostly cutting and assembly: "
                "less fire load than tanning.",
    "garments": "Fabric stock burns, but stitching is low-heat work with few ignition sources.",
    "textiles": "Spinning and weaving throw off lint and fibre dust that spread fire quickly.",
    "food_processing": "Ovens and fryers are ignition sources, but most stock does not burn easily.",
    "engineering": "Mostly metal that does not burn; hot work like welding and cutting is the main risk.",
    "chemicals": "Flammable and reactive materials: the highest fire load on this card.",
    "brassware": "Metal goods and casting furnaces, with little combustible stock.",
    "retail": "Shops and e-commerce fulfilment hold dense, mixed, often combustible stock, with public or "
              "high-turnover footfall: a mid-range fire load.",
    "warehousing": "Large volumes of stock stacked high in one place: a fire spreads fast and the loss "
                   "concentrates, so warehouses rate above most light manufacturing.",
    "office": "Desks, servers and paper, with no process heat: the lowest fire load on this card.",
    "other": "No specific class yet: a middle rate until the line of business is known.",
}

WC_WHY = {
    "leather": "Chemicals, wet floors and heavy hides: injury rates above light manufacturing.",
    "footwear": "Cutting and stitching machines: moderate injury risk.",
    "garments": "Sewing work: among the lowest injury rates in manufacturing.",
    "textiles": "Spinning and weaving machinery: moderate injury risk.",
    "food_processing": "Heat, knives and slippery floors: moderate injury risk.",
    "engineering": "Heavy machinery, presses and hot work: high injury risk.",
    "chemicals": "Burns, fumes and exposure: the highest injury risk on this card.",
    "brassware": "Furnaces and molten metal, at small scale: moderate injury risk.",
    "retail": "Shop-floor and stock handling: low to moderate injury risk.",
    "warehousing": "Manual lifting, forklifts and loading docks: moderate to high injury risk.",
    "office": "Desk work: the lowest injury risk on this card.",
    "other": "No specific class yet: a middle rate.",
}

MARINE_WHY = "Rated as a % of the insured value (cargo + 10%); international voyages carry more handling and transit risk than domestic ones."
LIABILITY_WHY = "Rated as a % of the limit of cover, scaled up for larger turnover: more sales means more exposure to claims."
STFI_WHY = "Storm, tempest, flood and inundation cover, priced on the sum insured whatever the trade."

LOADING_WHY = {
    "HEADCOUNT_UNDERSTATED": "Records show far more staff than declared. More people usually means more machinery, "
                             "stock and activity than the proposal describes, so the risk is bigger than disclosed.",
    "UNDECLARED_SITE": "Each location we found but were not told about is property, stock or people the policy could "
                       "end up covering without assessment. Charged for up to 3 sites; the rest are listed but free.",
    "UNDECLARED_HAZARD": "Job ads show hazardous work (boilers, tanning, dyeing) that the proposal did not mention. "
                         "It raises the fire load and was not disclosed.",
    "DISCLOSED_HAZARD": "The applicant confirmed the hazardous work when asked: priced for the extra fire load, "
                        "but no longer a disclosure problem.",
    "ADVERSE_EVENT": "News that names this company reports an incident. Past incidents are a strong predictor of future ones.",
    "CLAIMS_HISTORY_UNKNOWN": "Past claims are the best single predictor of future claims. Without them we price cautiously.",
    "DERIVED_VALUE": "Some values were estimated rather than stated: a small margin in case the estimate is off.",
    "UNDISCLOSED_ESSENTIAL": "The applicant said \"don't know\" to something only they can know, so we priced on our own "
                             "cautious estimate and added a penalty. Answering removes it.",
    "OCCUPANCY_MISMATCH": "Records show a riskier line of business than the one declared, so we price at the dearer "
                          "of the two rates.",
}
UNKNOWN_WHY = "Nobody could give this, so a margin covers the unknown."

MINIMUM_WHY = "No policy is issued below ₹10,000 before tax: the fixed cost of underwriting and servicing a policy."
GST_WHY = "GST on general insurance premiums in India is 18%."
