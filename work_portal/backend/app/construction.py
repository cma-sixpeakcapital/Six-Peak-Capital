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
- ``jobs[].client``: HVN | Six Peak affiliate | Third party | "" (unclassified). Drives the
  third-party backlog split (Chris, 11/1/2026).
- ``awards``: Tom Taggart's awarded-but-not-yet-signed third-party projects. Each counts toward
  gc_backlog_third_party at its expected value until the job appears signed in the KPI workbook
  (then the feed reports it as rolled into the books) or Tom marks it lost.
- ``notices``: temporary notes shown on the page (to be deleted later).

Editing is open, like everything else on the portal; every save is audited.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

DEFAULT_ROLES = ["Superintendent", "Project Manager", "Assistant PM", "Project Coordinator"]
CAUSE_CODES = {"", "owner", "weather", "LV", "sub"}
CLIENTS = {"", "HVN", "Six Peak affiliate", "Third party"}
AWARD_STATUSES = {"awarded", "signed", "lost"}
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

# Jobs in the GC Scorecard feed (04 Automation/GC Scorecard/RUNBOOK.md), with the
# frozen benchmark final-completion dates used as the stand-in until pay-app
# contract dates are entered (Chris, decision 1, 10/31/2026).
SEED_JOBS: list[dict[str, Any]] = [
    {"job": "Whipple",   "contract_completion": "2027-08-30", "client": "HVN"},
    {"job": "Califa",    "contract_completion": "2027-08-04", "client": "HVN"},
    {"job": "Nelrose",   "contract_completion": "2027-06-17", "client": "HVN"},
    {"job": "Ramsgate",  "contract_completion": "2027-09-13", "client": "Six Peak affiliate"},
    {"job": "Crenshaw",  "contract_completion": "2026-10-29", "client": "Six Peak affiliate"},
    {"job": "Riverton",  "contract_completion": "2028-02-18", "client": ""},
    {"job": "Lexington", "contract_completion": "2028-02-25", "client": ""},
    {"job": "Francis",   "contract_completion": "2029-03-05", "client": "Six Peak affiliate"},
    {"job": "Acama",     "contract_completion": "",           "client": "HVN"},
]
# Jobs on the KPI workbook's Contract & Backlog tab that are not yet signed (n/a rows), so the
# backlog feed can classify them the day they sign. Client per Chris 11/1/2026.
SEED_CLIENTS_PENDING: dict[str, str] = {"Troost": "HVN", "Klump": "Third party", "Scott": "Third party"}
SEED_SOURCE = "benchmark (pending pay app)"

SEED_NOTICES: list[dict[str, str]] = [
    {"id": "bob", "to": "Bob",
     "text": "The metrics tab gained two optional columns, green_low and yellow_ceiling, so the portal can color "
             "the two-sided utilization bands (70 / 80 / 100 / 110). Nothing else of yours changed, and your "
             "retired rows stay in the sheet; the portal now reads them quietly instead of flagging them. "
             "One thing to be aware of: % milestones still measures against the original benchmarks while "
             "jobs-behind now uses contract dates, so the two can disagree on a job."},
    {"id": "chris-andresen", "to": "Chris Andresen",
     "text": "This page is where the pay-app contract completion dates, cause codes, contingency explanations "
             "and the monthly utilization hours now go; the Monday 8:47 a.m. feed reads them from here and "
             "writes the number to the Sheet. The dates showing today are the frozen benchmark dates as a "
             "stand-in, flagged as such on the scorecard until you replace them with pay-app dates. For "
             "utilization, pick the month, enter Grady's required hours by job and role, and each person's "
             "available hours net of PTO and holidays; the preview row shows the result before you save."},
    {"id": "tom", "to": "Tom",
     "text": "Signed backlog is now split in two on the scorecard. Total LV backlog comes straight from the monthly "
             "KPI workbook. Third-party backlog is the signed third-party jobs from that workbook plus whatever you "
             "log in the Awards table below: a project awarded to LV (verbally or in writing) that has not signed "
             "yet, with its expected contract value. It counts at that value until the job shows up signed in the "
             "KPI workbook, when it rolls into the books automatically, or until you mark it lost. The old weekly "
             "signed-backlog row you typed into the Sheet is retired."},
    {"id": "grady", "to": "Grady",
     "text":
             "The construction scorecard changes on a trial basis starting Monday 11/2. Four numbers now come "
             "from your files with nothing to send: jobs behind contract date and % milestones on time (from "
             "the newest dated .mpp in each job's Box \"5. SCHEDULE\" folder; Califa from \"GRADYS SCHEDULES "
             "-\"), and contingency flags and the two backlog numbers (from Chris Andresen's monthly KPI "
             "workbook). Retired from the board: the old jobs-behind, contingency burn, buyout savings, jobs "
             "per PM, sub score and signed backlog. Buyout by job still goes to Chris Andresen monthly.\n\n"
             "You report two numbers each week: safety recordables, and subcontractors in default (out of "
             "money or not performing, off site 2+ weeks, or a supplier lien because the sub did not pay). "
             "One Slack line to Chris Aiello by Monday 8 a.m. ET is enough: \"Safety 0, subs in default 0\", "
             "with sub, job and issue for anything that is not zero. If nothing comes in, 0 goes on the "
             "board.\n\n"
             "Three things to settle: (1) Contract completion dates: 7 of the 9 jobs show the benchmark date "
             "as a stand-in and are flagged on the scorecard until the contract date from the signed schedule "
             "exhibit is entered in the jobs table below (you or Kim, about ten minutes). (2) Schedule files: "
             "keep saving dated .mpp files in the usual folder; look-aheads, templates and OLD folders are "
             "skipped, and a stale file repeats last month's answer (four files are more than 45 days old "
             "today). (3) Utilization: confirm the role list below (Superintendent, Project Manager, "
             "Assistant PM, Project Coordinator; edit the box and save if it needs changing) and send Chris "
             "Andresen November's required hours by role for each active job by Friday 11/6."},
]
_STAMP = "Temporary note (Chris Aiello, 10/31/2026). This box goes away once you have read it; click Remove."


def default_doc() -> dict[str, Any]:
    return {
        "roles": list(DEFAULT_ROLES),
        "jobs": [_job_row({**j, "active": True, "contract_source": SEED_SOURCE if j["contract_completion"] else ""})
                 for j in SEED_JOBS],
        "clients_pending": dict(SEED_CLIENTS_PENDING),
        "awards": [],
        "utilization": {},
        "notices": [dict(n) for n in SEED_NOTICES],
        "notice": "",
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
    if "awards" not in doc:
        # Migration 11/1/2026 (backlog split): client flags on the seeded jobs, pending-job clients, awards.
        seed_clients = {j["job"]: j.get("client", "") for j in SEED_JOBS}
        for j in doc["jobs"]:
            j.setdefault("client", seed_clients.get(j.get("job"), ""))
        doc["clients_pending"] = dict(SEED_CLIENTS_PENDING)
        doc["awards"] = []
        tom = next((n for n in SEED_NOTICES if n["id"] == "tom"), None)
        if tom and doc.get("notices") and not any(n.get("id") == "tom" for n in doc["notices"]):
            doc["notices"].append(dict(tom))
    if "notices" not in doc:
        # Migration 10/31/2026: the first deploy seeded one combined note; Chris asked for one per person.
        doc["notices"] = [dict(n) for n in SEED_NOTICES] if doc.get("notice") else []
        doc["notice"] = ""
    return doc


def set_notice(doc: dict[str, Any], note_id: str, to: str, text: str) -> dict[str, str]:
    """Create or replace one person's temporary note (Chris 11/1/2026: Grady's walkthrough goes in his note)."""
    nid = "".join(ch for ch in str(note_id or "").strip().lower() if ch.isalnum() or ch == "-")[:40]
    text = str(text or "").strip()[:4000]
    to = str(to or "").strip()[:60]
    if not nid or not text:
        raise ValueError("note id and text are required")
    notices = doc.setdefault("notices", [])
    for n in notices:
        if n.get("id") == nid:
            n["text"] = text
            if to:
                n["to"] = to
            return n
    entry = {"id": nid, "to": to or nid.title(), "text": text}
    notices.append(entry)
    return entry


def remove_notice(doc: dict[str, Any], note_id: str) -> bool:
    before = len(doc.get("notices") or [])
    doc["notices"] = [n for n in doc.get("notices") or [] if n.get("id") != note_id]
    return len(doc["notices"]) < before


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
    client = _str(r.get("client"), 30)
    if client not in CLIENTS:
        raise ValueError(f"{job}: client must be HVN, Six Peak affiliate, Third party (or blank)")
    return {
        "job": job,
        "active": bool(r.get("active", True)),
        "client": client,
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


def _money(v: Any, field: str) -> float:
    if v in ("", None):
        return 0.0
    try:
        x = float(str(v).replace(",", "").replace("$", ""))
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be a dollar amount")
    if x < 0 or x > 1e9:
        raise ValueError(f"{field} must be between 0 and $1B")
    return round(x, 2)


def set_awards(doc: dict[str, Any], awards: list[dict[str, Any]]) -> None:
    """Tom's awarded-not-yet-signed third-party projects."""
    rows = []
    for r in awards or []:
        project = _str(r.get("project"), 80)
        if not project:
            continue
        status = _str(r.get("status"), 10).lower() or "awarded"
        if status not in AWARD_STATUSES:
            raise ValueError(f"{project}: status must be awarded, signed or lost")
        rows.append({
            "project": project,
            "client": _str(r.get("client"), 80),
            "award_date": _iso_date(r.get("award_date"), f"{project}: award_date"),
            "expected_value": _money(r.get("expected_value"), f"{project}: expected value"),
            "expected_signing": _iso_date(r.get("expected_signing"), f"{project}: expected_signing"),
            "kpi_job": _str(r.get("kpi_job"), 60),
            "status": status,
            "notes": _str(r.get("notes"), 300),
        })
    names = [r["project"].lower() for r in rows]
    if len(names) != len(set(names)):
        raise ValueError("project names must be unique")
    doc["awards"] = rows


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
        "notices": list(doc.get("notices") or []),
        "clients_pending": dict(doc.get("clients_pending") or {}),
        "awards": list(doc.get("awards") or []),
    }
