"""Tests never touch the network or spend credits: force offline mode and a
throwaway data directory for the case store."""
import os
import tempfile

os.environ["INVARIANT_OFFLINE"] = "1"
os.environ.setdefault("INVARIANT_DATA", tempfile.mkdtemp(prefix="invariant-test-"))
