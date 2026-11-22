"""The decision hash: resolved company id + confirmed facts + rules version.

Never the wording, never the conversation, never fetch timestamps.
"""
from __future__ import annotations

import hashlib
import json
from typing import Iterable, Optional

from invariant.shapes import Fact


def _fact_key(f: Fact) -> dict:
    d = f.model_dump(mode="json")
    if d.get("source"):
        d["source"].pop("fetched", None)
    return d


def decision_hash(company_id: Optional[str], facts: Iterable[Fact], rules_version: str) -> str:
    payload = {
        "company_id": company_id,
        "facts": sorted((_fact_key(f) for f in facts), key=lambda d: d["id"]),
        "rules_version": rules_version,
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()
