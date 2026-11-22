"""The eight fixed rewrites. Files in the repo, never generated at demo time.

Each is the SAME RISK said differently. If the hashes differ, either the Read
step or the normalizer is leaking wording into the decision - that is a bug,
not something to hide.
"""
HERO = ("A leather exporter applying for cover says it has 120 employees across "
        "three units. Check that against public data and tell me what does not match.")

REWRITES = {
    "as given":        HERO,
    "terse":           "leather exporter, 120 employees, 3 units. what doesn't match?",
    "verbose":         ("Good morning. We have received a proposal from a company in the "
                        "leather export trade. In their submission they have declared a "
                        "total workforce of 120 employees, spread across three separate "
                        "manufacturing units. Could you please verify these declarations "
                        "against publicly available information and report any variances?"),
    "rude":            "just check this leather exporter already. 120 employees, 3 units. what are they hiding?",
    "numbers in words": ("A leather export business states its headcount is one hundred twenty "
                         "and that it operates three units. Verify against public data."),
    "typos":           "leather expoter sais 120 employes accross 3 unitss, pls chk wat dosnt match",
    "hinglish":        ("Ek leather exporter hai, bolta hai 120 employees hain aur teen units "
                        "hain. Public data se check karke batao kya match nahi ho raha."),
    "trade name":      ("Applicant trades as a leather goods exporter. Declared: 120 staff, "
                        "3 production sites. Please check the record."),
}
