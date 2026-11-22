"""decide/ must stay pure: no network, no LLM, no clock, no randomness."""
import ast
from pathlib import Path

DECIDE = Path(__file__).resolve().parents[1] / "invariant" / "decide"
BANNED = ("invariant.read", "invariant.evidence", "httpx", "requests", "anthropic", "datetime", "random",
          "time", "socket", "urllib", "os", "uuid", "secrets")


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                out.append(node.module)
            elif node.level and node.module in ("read", "evidence"):
                out.append("invariant." + node.module)
            elif node.level == 2:
                out += ["invariant." + (node.module or a.name) for a in node.names]
    return out


def test_decide_imports_nothing_impure():
    files = sorted(DECIDE.glob("*.py"))
    assert len(files) >= 8
    for f in files:
        for mod in _imports(f):
            assert not any(mod == b or mod.startswith(b + ".") for b in BANNED), f"{f.name} imports {mod}"
