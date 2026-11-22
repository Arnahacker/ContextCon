import sys, pathlib, yaml, pytest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from invariant.facts import Fact, Source

@pytest.fixture
def rules():
    p = pathlib.Path(__file__).resolve().parents[1] / "invariant" / "rules.yaml"
    return yaml.safe_load(p.read_text(encoding="utf-8"))

def src(what="POST /company/enrich", dated="2026-11-10", quote="x"):
    return Source(what=what, dated=dated, quote=quote)

def F(fid, fld, val, origin="crustdata", status="matches", kind="direct",
      match="company_id", source=None, note=""):
    if status != "cannot_verify" and source is None:
        source = src()
    return Fact(fid, fld, val, origin, status, kind, match, source, note)
