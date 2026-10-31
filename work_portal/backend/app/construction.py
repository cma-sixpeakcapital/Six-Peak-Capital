"""Construction inputs: the human-entered numbers behind Grady's GC scorecard.

Decided by Chris Aiello 10/31/2026 after Bob Kennedy's 10/28 metric changes.
Chris Andresen (and Grady) enter these on the portal instead of emailing them;
the Monday "gc-scorecard" feed reads them through GET /api/construction_inputs,
computes the metric, and the number still lands on the Sheet's actuals tab, so
Bob's Rule 1 (the Sheet is the only place a scorecard number is entered) holds.

What lives here (one document, key ``construction_inputs`` in the rocks doc so
history, restore and the change log come for free):

- ``jobs``: one row per LV job.
    contract_completion   the contract end date on the most recent pay app
                          (includes approved time extensions)  -> gc_jobs_behind_contract
    contract_source       where that date came from ("Pay app #12", or the
                          stand-in "benchmark (pending pay app)")
    cause_code            owner / weather / LV / sub, for a job running late
    contingency_note      one line explaining a contingency burn >= 1.0
- ``roles``: the utilization role list (Grady confirms; starts with Bob's four).
- ``utilization``: by month "YYYY-MM":
    required   {job: {role: hours}}   Grady's monthly staffing plan
    available  [{person, role, hours}] Chris Andresen, net of PTO and holidays
  -> gc_utilization_role = most stretched role's required / available.
- ``notice``: a temporary note shown on the page (to be deleted later).

Editing is open, like everything else on the portal; every save is audited.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

DEFAULT_ROLES = ["Superintendent", "Project Manager", "Assistant PM", "Project Coordinator"]
CAUSE_CODES = {"", "owner", "weather", "LV", "sub"}
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

# Jobs in the GC Scorecard feed (04 Automation/GC Scorecard/RUNBOOK.md), with the
# frozen benchmark final-completion dates used as the stand-in until pay-app
# contract dates are entered (Chris, decision 1, 10/31/2026).
SEED_JOBS: list[dict[str, Any]] = [
    {"job": "Whipple",   "contract_completion": "2027-08-30"},
    {"job": "Califa",    "contract_completion": "2027-08-04"},
    {"job": "Nelrose",   "contract_completion": "2027-06-17"},
    {"job": "Ramsgate",  "contract_completion": "2027-09-13"},
    {"job": "Crenshaw",  "contract_completion": "2026-10-29"},
    {"job": "Riverton",  "contract_completion": "2028-02-18"},
    {"job": "Lexington", "contract_completion": "2028-02-25"},
    {"job": "Francis",   "contract_completion": "2029-03-05"},
    {"job": "Acama",     "contract_completion": ""},
]
SEED_SOURCE = "benchmark (pending pay app)"

SEED_NOTICE = (
    "Temporary note (Chris Aiello, 10/31/2026; this box goes away once everyone has seen it). "
    "Bob: the metrics tab gained two columns, green_low and yellow_ceiling, so the portal can color "
    "the two-sided utilization bands; nothing else of yours changed. "
    "Chris Andresen: this is where the pay-app contract completion dates, cause codes, contingency "
    "explanations and the monthly utilization hours now go; the Monday feed reads them from here. "
    "The dates shown today are the frozen benchmark dates as a stand-in, flagged as such on the "
    "scorecard until you replace them. "
    "Grady: please confirm the role list below (Superintendent, Project Manager, Assistant PM, "
    "Project Coordinator) and send Chris Andresen November's hours by role per job by Fri 11/6."
)


def default_doc() -> dict[str, Any]:
    return {
        "roles": list(DEFAULT_ROLES),
        "jobs": [_job_row({**j, "active": True, "contract_source": SEED_SOURCE if j["contract_completion"] else ""})
                 for j in SEED_JOBS],
        "utilization": {},
        "notice": SEED_NOTICE,
        "updated_at": "",
    }


def get_doc(data: dict[str, Any]) -> dict[str, Any]:
    """The construction inputs document inside the rocks doc, seeded on first use."""
    doc = data.get("construction_inputs")
    if not isinstance(doc, dict):
        doc = default_doc()
        data["construction_inputs"] = doc
    doc.setdefault("roles", list(DEFAULT_ROLES))
    doc.setdefault("jobs", [])
    doc.setdefault("utilization", {})
    doc.setdefault("notice", "")
    return doc


# ----------------------------------------------------------------- validation
def _str(v: Any, limit: int = 300) -> str:
    return str(v or "").strip()[:limit]


def _iso_date(v: Any, field: str) -> str:
    s = _str(v, 10)
    if not s:
        return ""
    try:
        return date.fromisoformat(s).isoformat()
    except ValueError:
        raise ValueError(f"{field} must be a date (YYYY-MM-DD), got '{s}'")


def _hours(v: Any, field: str) -> float:
    if v in ("", None):
        return 0.0
    try:
        h = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be a number of hours")
    if h < 0 or h > 1000:
        raise ValueError(f"{field} must be between 0 and 1000 hours")
    return round(h, 1)


def _job_row(r: dict[str, Any]) -> dict[str, Any]:
    job = _str(r.get("job"), 60)
    if not job:
        raise ValueError("every job row needs a job name")
    cause = _str(r.get("cause_code"), 10)
    if cause not in CAUSE_CODES:
        raise ValueError(f"{job}: cause_code must be one of owner, weather, LV, sub (or blank)")
    return {
        "job": job,
        "active": bool(r.get("active", True)),
        "contract_completion": _iso_date(r.get("contract_completion"), f"{job}: contract_completion"),
        "contract_source": _str(r.get("contract_source"), 120),
        "pay_app_through": _iso_date(r.get("pay_app_through"), f"{job}: pay_app_through"),
        "cause_code": cause,
        "contingency_note": _str(r.get("contingency_note"), 300),
        "notes": _str(r.get("notes"), 300),
    }


def set_jobs(doc: dict[str, Any], jobs: list[dict[str, Any]], roles: list[str] | None = None) -> None:
    rows = [_job_row(r) for r in jobs]
    names = [r["job"].lower() for r in rows]
    if len(names) != len(set(names)):
        raise ValueError("job names must be unique")
    doc["jobs"] = rows
    if roles is not None:
        clean = [_str(x, 40) for x in roles if _str(x, 40)]
        if not clean:
            raise ValueError("at least one role is required")
        if len({c.lower() for c in clean}) != len(clean):
            raise ValueError("role names must be unique")
        doc["roles"] = clean


def set_utilization(doc: dict[str, Any], month: str, required: dict[str, Any],
                    available: list[dict[str, Any]], note: str = "") -> dict[str, Any]:
    if not MONTH_RE.match(month or ""):
        raise ValueError("month must look like 2026-11")
    roles = {r.lower(): r for r in doc.get("roles") or DEFAULT_ROLES}
    jobs = {j["job"].lower(): j["job"] for j in doc.get("jobs") or []}
    req: dict[str, dict[str, float]] = {}
    for job, by_role in (required or {}).items():
        jname = jobs.get(_str(job).lower())
        if jname is None:
            raise ValueError(f"required hours: unknown job '{job}'")
        if not isinstance(by_role, dict):
            raise ValueError(f"required hours for {jname} must be a role -> hours map")
        row: dict[str, float] = {}
        for role, h in by_role.items():
            rname = roles.get(_str(role).lower())
            if rname is None:
                raise ValueError(f"required hours: unknown role '{role}'")
            hours = _hours(h, f"{jname} / {rname} required hours")
            if hours:
                row[rname] = hours
        if row:
            req[jname] = row
    avail: list[dict[str, Any]] = []
    for a in available or []:
        person = _str(a.get("person"), 60)
        rname = roles.get(_str(a.get("role")).lower())
        if not person:
            continue
        if rname is None:
            raise ValueError(f"available hours: unknown role '{a.get('role')}' for {person}")
        avail.append({"person": person, "role": rname,
                      "hours": _hours(a.get("hours"), f"{person} available hours")})
    entry = {"required": req, "available": avail, "note": _str(note, 300)}
    doc.setdefault("utilization", {})[month] = entry
    return entry


# ------------------------------------------------------------------ compute
def utilization_summary(doc: dict[str, Any], month: str) -> dict[str, Any] | None:
    """The same arithmetic the Monday feed uses, so the page can preview it.

    Returns {month, roles: [{role, required, available, pct}], jobs: [...],
    highest: {role, pct}} or None when the month has no hours yet.
    """
    entry = (doc.get("utilization") or {}).get(month)
    if not entry:
        return None
    roles = list(doc.get("roles") or DEFAULT_ROLES)
    req_by_role = {r: 0.0 for r in roles}
    for job, by_role in (entry.get("required") or {}).items():
        for role, h in by_role.items():
            req_by_role[role] = req_by_role.get(role, 0.0) + float(h)
    avail_by_role = {r: 0.0 for r in roles}
    for a in entry.get("available") or []:
        avail_by_role[a["role"]] = avail_by_role.get(a["role"], 0.0) + float(a["hours"])
    rows = []
    for r in roles:
        req, av = req_by_role.get(r, 0.0), avail_by_role.get(r, 0.0)
        pct = round(100 * req / av) if av else None
        rows.append({"role": r, "required": req, "available": av, "pct": pct})
    scored = [x for x in rows if x["pct"] is not None and (x["required"] or x["available"])]
    if not scored:
        return None
    highest = max(scored, key=lambda x: x["pct"])
    jobs = [{"job": j, "hours": sum(float(h) for h in by_role.values()), "by_role": by_role}
            for j, by_role in (entry.get("required") or {}).items()]
    return {"month": month, "roles": rows, "jobs": jobs,
            "highest": {"role": highest["role"], "pct": highest["pct"]},
            "note": entry.get("note", "")}


def feed_view(doc: dict[str, Any]) -> dict[str, Any]:
    """What GET /api/construction_inputs returns to the Monday feed."""
    months = sorted((doc.get("utilization") or {}).keys())
    return {
        "roles": list(doc.get("roles") or DEFAULT_ROLES),
        "jobs": list(doc.get("jobs") or []),
        "utilization": {m: utilization_summary(doc, m) for m in months},
        "utilization_raw": doc.get("utilization") or {},
        "notice": doc.get("notice", ""),
    }
