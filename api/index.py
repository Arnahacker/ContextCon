"""Vercel entry point. Serverless disks are read-only except /tmp, so the case store and
caches live there (they reset when the instance is recycled)."""
import os

os.environ.setdefault("INVARIANT_DATA", "/tmp/invariant")

from invariant.api.app import app  # noqa: E402,F401
