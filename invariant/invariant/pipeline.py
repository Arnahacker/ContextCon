"""Read -> Check -> Decide. The only place the steps are wired together."""
from __future__ import annotations
import copy, hashlib, json, os, pathlib, uuid, yaml
from typing import Any, Callable, Optional

from .schemas import Form
from .facts import Fact, Source, CANNOT_VERIFY
from .read_step import extract
from .normalize import to_occupancy, money_to_int
from .identity import resolve, Identity
from .evidence.crustdata import Crustdata, EvidenceUnavailable
from .ledger import Ledger
from .budget import Budget, BudgetExceeded
from .runlog import RunLog
from . import build
from . import adapt
from .decide import decide
from .assume import assume_for_pricing
from .explain import price_questions, would_change_my_mind
from . import summary

RULES_PATH = pathlib.Path(__file__).with_name("rules.yaml")


def load_rules() -> dict[str, Any]:
    return yaml.safe_load(RULES_PATH.read_text(encoding="utf-8"))


class BadRulesPatch(ValueError):
    pass


def apply_rules_patch(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Edited rules from the screen: {"loadings.UNDECLARED_HAZARD.multiplier": 1.6}.

    Only EXISTING NUMERIC values can change - no new keys, no text, no
    structure - so a patch can move a price but cannot add a rule.
    The version gets a suffix derived from the patch itself, so the decision
    hash moves with the rules. Same patch, same version, same hash.
    """
    if not patch:
        return base
    out = copy.deepcopy(base)
    clean: dict[str, float] = {}
    for path, val in patch.items():
        keys = str(path).split(".")
        node = out
        for k in keys[:-1]:
            if not isinstance(node, dict) or k not in node:
                raise BadRulesPatch(f"no such rule: {path}")
            node = node[k]
        leaf = keys[-1]
        if not isinstance(node, dict) or leaf not in node:
            raise BadRulesPatch(f"no such rule: {path}")
        if isinstance(node[leaf], bool) or not isinstance(node[leaf], (int, float)):
            raise BadRulesPatch(f"not a number: {path}")
        try:
            v = float(val)
        except (TypeError, ValueError):
            raise BadRulesPatch(f"{path} must be a number, got {val!r}")
        if not (0 <= v <= 1e9):
            raise BadRulesPatch(f"{path} out of range: {v}")
        if v != node[leaf]:
            node[leaf] = v
            clean[path] = v
    if clean:
        tag = hashlib.sha256(json.dumps(clean, sort_keys=True).encode()).hexdigest()[:6]
        out["version"] = f"{base['version']}+edit.{tag}"
        out["_edited"] = clean
    return out


def run(prompt: str, run_id: Optional[str] = None,
        answers: Optional[dict[str, Any]] = None,
        rules: Optional[dict] = None,
        on_event: Optional[Callable[[dict], None]] = None) -> dict[str, Any]:
    """One prompt in, one full case out. Safe to call again with the same run_id.

    on_event, if given, is told about each stage and each API call as it
    happens. It only observes; nothing it does reaches the decision.
    """
    rules = rules or load_rules()
    run_id = run_id or uuid.uuid4().hex[:10]
    log = RunLog(run_id)

    def emit(**ev):
        if on_event:
            try:
                on_event(ev)
            except Exception:
                pass

    ledger = Ledger(listener=lambda e: emit(type="call", **e.to_dict()))
    budget = Budget(max_seconds=float(os.environ.get("MAX_SECONDS", 90)),
                    max_credits=float(os.environ.get("MAX_CREDITS", 400))).start()
    crust = Crustdata(ledger)
    facts: list[Fact] = []
    log.append("prompt", text=prompt)

    # 1. READ ------------------------------------------------------------
    emit(type="stage", name="read", text="Reading the submission into a fixed form")
    form = extract(prompt)
    emit(type="stage", name="form", form=form.to_dict())
    log.append("form", **form.to_dict())

    # answers from the conversation are declared facts with their own source.
    # "4.5 cr" becomes 45000000 here, and the UI echoes it back for confirmation.
    clean_answers: dict[str, Any] = {}
    for fld, val in (answers or {}).items():
        if val in (None, ""):
            continue
        if fld.endswith("_inr"):
            val = money_to_int(val)
            if val is None:
                continue
        clean_answers[fld] = val
    answers = clean_answers

    for fld, val in (answers or {}).items():
        setattr(form, fld, val) if hasattr(form, fld) else None
        facts.append(Fact(f"ans_{fld}", fld, val, "applicant_followup", "matches",
                          "direct", None,
                          Source(what="answered in the follow-up conversation",
                                 quote=str(val))))

    facts += [f for f in build.declared_facts(form)
              if f.field not in (answers or {})]

    # 2. CHECK -----------------------------------------------------------
    ident = Identity(rung=2)
    try:
        emit(type="stage", name="identify", text="Working out which company this is")
        ident = resolve(form, crust)
        facts.append(ident.fact())
        budget.check(ledger.credits)

        if ident.company:
            cid = ident.company.get("company_id")
            # identify already handed us company_data; only call enrich if not
            cd = ident.company.get("_cd") or {}
            if not cd.get("headcount"):
                cd = (adapt.matches(crust.enrich(crustdata_company_ids=[cid]))
                      or [{"data": {}}])[0]["data"]

            url = adapt.profile_url(cd)
            dated = adapt.headcount_dated(cd)

            # --- who they are, so the screen can show it with a link
            facts.append(Fact("co_name", "company_name", adapt.name(cd), "crustdata",
                              "matches", "direct", "company_id",
                              Source(what="POST /company/enrich -> basic_info.name",
                                     url=url, dated=dated, quote=adapt.name(cd) or "")))
            if adapt.year_founded(cd):
                facts.append(Fact("co_founded", "year_founded", adapt.year_founded(cd),
                                  "crustdata", "matches", "direct", "company_id",
                                  Source(what="POST /company/enrich -> basic_info.year_founded",
                                         url=url, quote=str(adapt.year_founded(cd)))))
            if adapt.employee_range(cd):
                facts.append(Fact("co_range", "employee_count_range",
                                  adapt.employee_range(cd), "crustdata", "matches",
                                  "proxy_range", "company_id",
                                  Source(what="POST /company/enrich -> basic_info.employee_count_range",
                                         url=url, quote=adapt.employee_range(cd))))
            spec = adapt.specialities(cd)
            if spec:
                facts.append(Fact("co_spec", "stated_activities", ", ".join(spec[:6]),
                                  "crustdata", "matches", "direct", "company_id",
                                  Source(what="POST /company/enrich -> taxonomy.professional_network_specialities",
                                         url=url, quote=", ".join(spec))))
            roles = adapt.role_mix(cd)
            if roles:
                facts.append(Fact("co_roles", "role_mix",
                                  ", ".join(f"{k} {v}" for k, v in roles.items()),
                                  "crustdata", "matches", "direct", "company_id",
                                  Source(what="POST /company/enrich -> headcount.by_role_absolute",
                                         url=url, dated=dated,
                                         quote=", ".join(f"{k}: {v}" for k, v in roles.items()))))

            # --- the GSTIN, if given: what the number proves about itself
            loc = cd.get("locations") or {}
            facts += build.gstin_facts(form.gstin, form.company_name or adapt.name(cd),
                                       loc.get("state") or adapt.hq(cd))

            # --- headcount, one-directional
            facts += build.headcount_facts(
                form.declared_headcount, adapt.headcount_total(cd),
                rules["tolerances"]["headcount_over_declared_pct"],
                Source(what="POST /company/enrich -> headcount.total", url=url,
                       dated=dated,
                       quote=f"total: {adapt.headcount_total(cd)} employees on record"))

            # --- growth: Crustdata computes it, do not recompute
            yoy = adapt.growth_yoy_pct(cd)
            if yoy is not None:
                facts.append(Fact("growth", "headcount_growth_pct", yoy, "crustdata",
                                  "matches", "direct", "company_id",
                                  Source(what="POST /company/enrich -> headcount.growth_percent.yoy",
                                         url=url, dated=dated, quote=f"yoy: {yoy}%")))

            # --- premises, from the address list only (see adapt.sites)
            prem = adapt.sites(cd)
            facts += build.site_facts(
                form.declared_sites, [{"city": c} for c in prem],
                "POST /company/enrich -> locations.all_office_addresses", url=url)

            # --- staff in another country. CONTEXT, not an undeclared site:
            # people on a payroll abroad are usually sales agents or buying
            # offices, not premises, and fire cover is about premises. Loading
            # it as a site would invent a finding. Shown, never priced.
            for region, n in adapt.offshore_regions(cd).items():
                facts.append(Fact(f"offshore_{region[:10]}", "staff_abroad", region,
                                  "crustdata", "consistent_unconfirmed", "lower_bound",
                                  "company_id",
                                  Source(what="POST /company/enrich -> headcount.by_region_absolute",
                                         url=url, dated=dated,
                                         quote=f"{n} staff recorded in {region}")))

            # --- occupancy from what the company says it does
            if not any(f.field == "occupancy" for f in facts):
                occ = to_occupancy(adapt.industry(cd), [adapt.activity_text(cd)])
                facts.append(Fact("occ_record", "occupancy", occ, "crustdata",
                                  "matches", "direct", "company_id",
                                  Source(what="POST /company/enrich -> taxonomy.professional_network_industry",
                                         url=url, quote=(adapt.industry(cd) or "")[:160])))

            # --- certifications = DISCOUNTS, free from basic_info.description
            for code, proof in adapt.certifications(cd):
                if code in rules["discounts"]:
                    facts.append(Fact(f"cert_{code}", "certification", code, "crustdata",
                                      "matches", "direct", "company_id",
                                      Source(what="POST /company/enrich -> basic_info.description",
                                             url=url, quote=proof)))
            budget.check(ledger.credits)

            # --- hazardous work shows up in hiring first
            emit(type="stage", name="jobs", text="Checking job listings for hazardous work")
            try:
                jobs = adapt.jobs(crust.jobs_for_company(cid), company_id=cid)
            except EvidenceUnavailable:
                jobs = []
            # listings older than a year are not evidence about the site today
            import datetime as _dt
            jobs, stale_jobs = adapt.recent_jobs(jobs, _dt.date.today().isoformat())
            if stale_jobs:
                newest = max((j.get("posted") or "" for j in stale_jobs), default="")
                facts.append(Fact("jobs_stale", "stale_job_listings", len(stale_jobs),
                                  "crustdata", "consistent_unconfirmed", "lower_bound",
                                  "company_id",
                                  Source(what="POST /job/search -> metadata.date_added",
                                         dated=newest or None,
                                         quote=f"{len(stale_jobs)} listings older than a year"),
                                  note="older than 12 months: not used as evidence "
                                       "about the premises today"))
            # what the broker DID declare: a chemical maker has not hidden
            # "chemical handling" by saying it makes chemicals
            declared_work = list(form.activities or []) + [form.industry or ""]
            facts += build.hazard_facts(jobs, declared_work)
            home = ((cd.get("locations") or {}).get("country")
                    or (cd.get("headcount") or {}).get("largest_headcount_country")
                    or "India")
            facts += build.job_location_facts(jobs, prem, form.declared_sites, home)

            # --- hazard the company itself describes
            facts += build.hazard_facts(
                [{"title": adapt.activity_text(cd)[:400],
                  "url": (adapt.basic(cd) or {}).get("website")}], declared_work,
                src_what="POST /company/enrich -> basic_info.description + taxonomy")
            budget.check(ledger.credits)

            emit(type="stage", name="web", text="Searching the web for fires, accidents, notices")
            nm = adapt.name(cd) or ""
            city = adapt.hq(cd) or ""
            queries = [f'"{nm}" fire', f'"{nm}" accident', f'"{nm}" pollution notice']
            # a timeout raises EvidenceUnavailable -> the outer handler -> HOLD
            web = crust.web_search(" OR ".join(queries))
            facts += build.adverse_facts(adapt.web_results(web), nm,
                                         city.split(",")[0], queries,
                                         complete=adapt.web_ok(web))
            budget.check(ledger.credits)

        elif form.gstin and not ident.candidates:
            facts += build.gstin_facts(form.gstin, form.company_name)
        elif ident.candidates:
            # rung 2: cannot check this company, so check the class it is in
            facts += build.cohort_facts(ident.candidates, form.declared_headcount,
                                        getattr(ident, "cohort_total", None))

    except EvidenceUnavailable as e:
        facts.append(Fact("ev_down", "evidence_unavailable", e.what, "derived",
                          CANNOT_VERIFY, note=e.why))
        log.append("evidence_unavailable", what=e.what, why=e.why)
    except BudgetExceeded as e:
        facts.append(Fact("ev_budget", "evidence_unavailable", f"{e.what} ceiling",
                          "derived", CANNOT_VERIFY, note=str(e)))
        log.append("budget_exceeded", what=e.what, spent=e.spent, cap=e.cap)

    # 3. DECIDE ----------------------------------------------------------
    emit(type="stage", name="decide", text="Deciding: a pure function of the facts")
    d = decide(facts, rules)
    provisional = decide(assume_for_pricing(facts), rules)
    questions = price_questions(facts, rules)
    flips = would_change_my_mind(facts, rules)
    log.append("decision", outcome=d.outcome, hash=d.hash, premium=d.premium_inr)

    out = {
        "run_id": run_id,
        "prompt": prompt,
        "form": form.to_dict(),
        "identity": {"rung": ident.rung, "assumed": ident.assumed,
                     "company": ident.company,
                     "candidates": (ident.candidates or [])[:6]},
        "facts": [f.to_dict() for f in facts],
        "decision": d.to_dict(),
        "provisional_premium_inr": provisional.premium_inr,
        "questions": [q.to_dict() for q in questions],
        "would_change_my_mind": flips,
        "ledger": ledger.to_dict(),
        "elapsed_s": budget.elapsed,
        "rules_version": rules["version"],
        "rules_edited": rules.get("_edited") or {},
        "price_build": price_build(d.to_dict(), rules),
        # when the gate is blocked the real build is empty; this one runs on the
        # labelled assumptions and is shown as PROVISIONAL, never as the price
        "provisional_price_build": price_build(provisional.to_dict(), rules),
        "assumed": [f.to_dict() for f in assume_for_pricing(facts) if f.origin == "derived"
                    and f.note == "assumed"],
    }
    out["gap_table"] = gap_table(out)
    out["headline"] = summary.headline(out)
    out["findings"] = summary.findings(out)
    out["unchecked"] = summary.unchecked(out)
    out["price_story"] = summary.price_story(out)
    return out


def price_build(d: dict, rules: dict) -> list[dict]:
    """The premium as a running total, step by step, for the waterfall.

    Recomputes nothing new: it replays decide()'s own steps in decide()'s order
    (base, each multiplier, the minimum, GST) and checks it lands on the same
    number. If it ever does not, it says so instead of drawing a wrong chart.
    """
    steps = d.get("steps") or []
    base_step = next((s for s in steps if "_BASE_" in s["rule"]), None)
    if not base_step or not d.get("premium_inr"):
        return []
    # the base amount is in the explain text's numbers; rebuild it from rate x basis
    import re as _re
    m = _re.search(r"([\d,]+(?:\.\d+)?) / (\d+) x ([\d.]+)", base_step.get("explain", ""))
    if not m:
        return []
    basis, per, rate = float(m.group(1).replace(",", "")), float(m.group(2)), float(m.group(3))
    total = basis / per * rate
    out = [{"label": "Base rate", "rule": base_step["rule"], "kind": "base",
            "multiplier": rate, "after": round(total), "because": base_step["because"],
            "explain": base_step.get("explain", "")}]
    for s in steps:
        if s is base_step or "_BASE_" in s["rule"]:
            continue
        before = total
        total *= s["multiplier"]
        out.append({"label": s["rule"].replace("_", " ").title(), "rule": s["rule"],
                    "kind": "load" if s["multiplier"] > 1 else "discount",
                    "multiplier": s["multiplier"], "delta": round(total - before),
                    "after": round(total), "because": s["because"],
                    "explain": s.get("explain", "")})
    floor = rules["minimum_premium_inr"]
    if total < floor:
        out.append({"label": "Minimum premium", "rule": "MINIMUM", "kind": "load",
                    "multiplier": None, "delta": round(floor - total), "after": floor,
                    "because": [], "explain": f"no policy below Rs {floor:,}"})
        total = floor
    before = total
    total *= 1 + rules["gst_rate"]
    out.append({"label": "GST", "rule": "GST", "kind": "tax",
                "multiplier": 1 + rules["gst_rate"], "delta": round(total - before),
                "after": round(total), "because": [],
                "explain": f"{rules['gst_rate'] * 100:.0f}% GST"})
    if round(total) != d["premium_inr"]:
        return [{"label": "price build does not reconcile with decide()", "kind": "error",
                 "after": d["premium_inr"], "because": [], "explain": ""}]
    return out


def gap_table(case: dict) -> list[dict]:
    """Said / record / gap / source, for the screen."""
    rows = []
    byf: dict[str, list[dict]] = {}
    for f in case["facts"]:
        byf.setdefault(f["field"], []).append(f)
    for fld, fs in byf.items():
        said = next((f for f in fs if f["origin"] in ("declared", "applicant_followup")), None)
        rec = next((f for f in fs if f["origin"] in ("crustdata", "web", "own_site")), None)
        if said is None and rec is None:
            continue
        # a declared value with no record behind it was NOT verified. Saying
        # "matches" there would be exactly the overclaiming this product exists
        # to stop.
        status = rec["status"] if rec else (
            "unchecked" if said and said["origin"] in ("declared", "applicant_followup")
            else said["status"])
        rows.append({
            "field": fld,
            "said": said["value"] if said else None,
            "record": rec["value"] if rec else None,
            "status": status,
            "source": (rec or said)["source"],
            "note": (rec or said).get("note", ""),
        })
    order = {"contradicts": 0, "undeclared": 1, "cannot_verify": 2, "unchecked": 3}
    rows.sort(key=lambda r: order.get(r["status"], 3))
    return rows
