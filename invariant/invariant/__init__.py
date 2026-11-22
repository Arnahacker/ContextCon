"""Load .env on import, so the app behaves the same on cmd, PowerShell and bash.

No python-dotenv dependency: it is six lines. Real environment variables
always win over the file.
"""
import os, pathlib

def _load_env(path: str = ".env") -> None:
    p = pathlib.Path(path)
    if not p.exists():
        p = pathlib.Path(__file__).resolve().parents[1] / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and v and k not in os.environ:   # a real env var always wins
            os.environ[k] = v

_load_env()
