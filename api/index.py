"""Vercel entry point. Serverless disks are read-only except /tmp, so the case store and
caches live there (they reset when the instance is recycled)."""
import os
import sys
from pathlib import Path

os.environ.setdefault("INVARIANT_DATA", "/tmp/invariant")
os.environ.setdefault("PYTHONUTF8", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # the repo root, so `invariant` imports

from invariant.api.app import app  # noqa: E402,F401
