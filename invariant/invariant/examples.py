"""Example submissions for the screen, one per trade.

These are HYPOTHETICAL broker submissions about real companies: the declared
numbers are invented to exercise the checks, the evidence is live Crustdata.
Each one was run end to end against the live API on 2026-11-22 (see
`verified`) before being listed. Do not add one without doing the same.
"""
EXAMPLES = [
    {"label": "Leather goods exporter, Kolkata",
     "trade": "leather goods",
     "prompt": ("Rajda Industries Exports Pvt Ltd, a leather exporter, says it has 120 "
                "employees across three units. Check against public data."),
     "verified": True},
    # identify: the exact name "Superhouse LTD" (superhousegroup.com,
    # 1001-5000) scores 0.60 under five 0.80 lookalikes. Exact name wins.
    {"label": "Tannery, Kanpur",
     "trade": "leather tanning",
     "prompt": ("Superhouse Limited, a leather tannery, says it has 900 employees "
                "across two units. Check the declaration against public data."),
     "verified": True},
    # identify: Bharat Leather, Bharat Leather Enterprises, ...Corporation,
    # ...Work, ...Works - all 0.60, none is the name given. It HOLDS: correct.
    {"label": "Ambiguous name: holds, never guesses",
     "trade": "leather",
     "prompt": ("Bharat Leather Industries, a leather goods maker, says it has 60 "
                "employees at one unit. Check against public data."),
     "verified": True},
    {"label": "Chemical manufacturer, Pune",
     "trade": "chemicals",
     "prompt": ("Sudarshan Chemical Industries Limited, a chemical pigment maker, "
                "declares 800 employees at two plants. What does not match?"),
     "verified": True},
    {"label": "Garment exporter, Bengaluru",
     "trade": "garments",
     "prompt": ("Gokaldas Exports Ltd, a garment stitching exporter, says it has 2000 "
                "workers across five factories. Verify against public records."),
     "verified": True},
    {"label": "Cold storage, logistics",
     "trade": "cold storage",
     "prompt": ("Snowman Logistics Limited runs cold storage warehouses and declares "
                "300 staff at four sites. Check what does not match."),
     "verified": True},
    {"label": "No company named",
     "trade": "leather (class check)",
     "prompt": ("A leather exporter applying for cover says it has 120 employees across "
                "three units. Check that against public data and tell me what does not match."),
     "verified": True},
]
