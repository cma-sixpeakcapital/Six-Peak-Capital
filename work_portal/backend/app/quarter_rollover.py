"""Generic quarter rollover for the L10 ``rocks_doc`` — pure, idempotent.

Generalises the one-time ``q3_migration.py`` so every quarter close is the same
reviewable transform (``scripts/rollover_quarter.py`` is the CLI):

  1. **Close out** the outgoing quarter: stamp a binary ``result`` on every rock
     of ``from_quarter`` (``complete | carry_forward | task | killed | deferred``),
     record ``result_note`` / ``root_cause``, create a to-do for each ``task``
     disposition (or link an existing one), and link each ``carry_forward`` to
     its successor rock in the new quarter (``successor_id``).
  2. **Archive** every ``from_quarter`` rock (``archived=true``). Nothing is
     deleted; the Scoreboard reads the archived rocks' ``result`` fields.
  3. **Load** the new quarter's rocks (company force-ranked + individual by
     owner) and register the quarter in ``data["quarters"]``.
  4. Apply any **fixups** (e.g. a rock missing its quarter tag).

Idempotency: results are only stamped where absent or different (re-run =
no-op), to-dos are keyed on the source rock id, loads are keyed on
(level, owner, title, quarter), quarter registration is keyed on id.

Scoring rules live in ``scoring.py``; this module only records results.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

RESULTS = {"complete", "carry_forward", "task", "killed", "deferred"}

STATUS_MAP = {
    "open": "incomplete",
    "in_progress": "in_progress",
    "deferred": "incomplete",
    "complete": "complete",
    "incomplete": "incomplete",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: str | Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def iter_rocks(data: dict[str, Any]):
    """Yield (owner_key_or_None, rock) for every rock, company first."""
    for rock in data.get("company_rocks", []) or []:
        yield None, rock
    for owner, rocks in (data.get("rocks", {}) or {}).items():
        for rock in rocks:
            yield owner, rock


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower().replace("\u2019", "'")).strip()


def _find_rock(data: dict[str, Any], entry: dict[str, Any],
               quarter: str | None = None) -> dict[str, Any] | None:
    """Locate a rock by ``id`` first (authoritative), else by normalised title."""
    rid = entry.get("id")
    if rid:
        for _o, rock in iter_rocks(data):
            if rock.get("id") == rid:
                return rock
    return _find_by_title(data, entry.get("title", ""), entry.get("owner"), quarter)


def _find_by_title(data: dict[str, Any], title: str, owner: str | None = None,
                   quarter: str | None = None) -> dict[str, Any] | None:
    """Locate a rock by normalised title (and owner / quarter when given)."""
    t = _norm(title)
    best = None
    for owner_key, rock in iter_rocks(data):
        if _norm(rock.get("title")) != t:
            continue
        if quarter and rock.get("quarter") not in (quarter, None, ""):
            continue
        rock_owner = rock.get("owner") or owner_key or ""
        if owner and rock_owner != owner and owner_key != owner:
            continue
        best = rock
        break
    return best


def _rock_exists(rocks: list[dict[str, Any]], *, title: str, owner: str,
                 quarter: str, level: str) -> dict[str, Any] | None:
    for r in rocks:
        if (r.get("title") == title and r.get("quarter") == quarter
                and r.get("level") == level and r.get("owner") == owner):
            return r
    return None


def _todo_for_rock(data: dict[str, Any], rock_id: str) -> dict[str, Any] | None:
    for t in data.get("todos", []) or []:
        if (t.get("source") or {}).get("rock_id") == rock_id:
            return t
    return None


def _todo_matching(data: dict[str, Any], owner: str, needle: str) -> dict[str, Any] | None:
    """Find an open to-do by owner + a case-insensitive substring of its task."""
    n = (needle or "").lower()
    if not n:
        return None
    for t in data.get("todos", []) or []:
        if t.get("completed"):
            continue
        if (t.get("owner") or "") == owner and n in (t.get("task") or "").lower():
            return t
    return None


# --- step 1: close out the outgoing quarter --------------------------------

def close_out_quarter(data: dict[str, Any], from_quarter: str,
                      closeout: list[dict[str, Any]], plan: dict[str, Any]) -> None:
    data.setdefault("todos", [])
    for n, entry in enumerate(closeout, start=1):
        result = entry.get("result", "")
        if result not in RESULTS:
            plan["closeout_invalid"].append({"title": entry.get("title"), "result": result})
            continue
        rock = _find_rock(data, entry, from_quarter)
        if rock is None:
            plan["closeout_missing"].append(entry.get("title"))
            continue
        rock_id = rock.get("id") or f"r_{from_quarter.replace(' ', '').lower()}_{n:02d}"
        rock["id"] = rock_id

        changed = False
        if rock.get("result") != result:
            rock["result"] = result
            rock["result_at"] = _now()
            changed = True
        for src, dst in (("root_cause", "root_cause"), ("note", "result_note"),
                         ("rule", "q_rule"), ("successor", "successor_title")):
            if entry.get(src) and rock.get(dst) != entry[src]:
                rock[dst] = entry[src]
                changed = True
        # A complete result must agree with the status the toggle shows.
        if result == "complete" and rock.get("status") != "complete":
            rock["status"] = "complete"
            changed = True
        if result in ("carry_forward", "task", "killed") and rock.get("status") == "complete":
            rock["status"] = "incomplete"
            changed = True
        (plan["closeout_stamped"] if changed else plan["closeout_unchanged"]).append(
            {"title": rock["title"], "owner": rock.get("owner") or entry.get("owner"), "result": result})

        # Task disposition -> a to-do owned by the individual (or link an existing one).
        if result == "task":
            todo_spec = entry.get("todo") or {}
            existing = _todo_for_rock(data, rock_id)
            if existing is None and todo_spec.get("link_existing"):
                existing = _todo_matching(data, todo_spec.get("owner", ""), todo_spec["link_existing"])
                if existing is not None:
                    existing.setdefault("source", {})
                    existing["source"].setdefault("rock_id", rock_id)
                    existing["source"].setdefault("label", f"from rock ({from_quarter})")
            if existing is not None:
                plan["todos_linked"].append({"todo_id": existing.get("id"), "task": existing.get("task"),
                                             "rock": rock["title"]})
            else:
                owner = todo_spec.get("owner") or rock.get("owner") or entry.get("owner") or ""
                todo = {
                    "id": f"td_{from_quarter.replace(' ', '').lower()}conv_{n:02d}",
                    "owner": owner,
                    "task": todo_spec.get("task") or rock.get("title", ""),
                    "detail": todo_spec.get("note", "") or "",
                    "due": todo_spec.get("due", "") or rock.get("due", "") or "",
                    "completed": False,
                    "created_at": _now(),
                    "source": {"type": "rock", "rock_id": rock_id, "owner": owner,
                               "quarter": from_quarter, "label": f"from rock ({from_quarter})"},
                }
                data["todos"].append(todo)
                plan["todos_created"].append({"todo_id": todo["id"], "owner": owner,
                                              "task": todo["task"], "due": todo["due"]})


# --- step 2: archive the outgoing quarter ----------------------------------

def archive_quarter(data: dict[str, Any], from_quarter: str, plan: dict[str, Any]) -> None:
    for owner_key, rock in iter_rocks(data):
        if rock.get("quarter") != from_quarter:
            continue
        if rock.get("archived"):
            plan["archive_skipped"].append(rock.get("title"))
            continue
        rock["archived"] = True
        plan["archived"].append({"title": rock.get("title"),
                                 "owner": rock.get("owner") or owner_key or "Company",
                                 "result": rock.get("result", "")})


# --- step 3: load the new quarter ------------------------------------------

def _build_rock(entry: dict[str, Any], rid: str, quarter: str, *, deferred: bool) -> dict[str, Any]:
    rock = {
        "id": rid,
        "level": entry["level"],
        "owner": entry["owner"],
        "title": entry["title"],
        "area": entry.get("area", ""),
        "priority": entry.get("priority"),
        "rank": entry.get("rank"),
        "due": entry.get("due_date", ""),
        "due_date": entry.get("due_date", ""),
        "status": STATUS_MAP.get(entry.get("status", "open"), "incomplete"),
        "done_definition": entry.get("done_definition", ""),
        "smart_statement": entry.get("smart_statement", ""),
        "controllable_action": entry.get("controllable_action", ""),
        "milestones": entry.get("milestones") or {},
        "dependencies": entry.get("dependencies", ""),
        "dependency_risk": entry.get("dependency_risk", ""),
        "ties_to_vto": entry.get("ties_to_vto", ""),
        "source": entry.get("source", ""),
        "review_status": entry.get("review_status", ""),
        "notes": entry.get("notes", ""),
        "quarter": entry.get("quarter", quarter),
        "archived": False,
        "deferred": deferred,
    }
    return rock


def load_quarter(data: dict[str, Any], to_quarter: str, new: dict[str, Any],
                 plan: dict[str, Any]) -> None:
    data.setdefault("company_rocks", [])
    data.setdefault("rocks", {})
    data.setdefault("team", [])
    team_names = {p.get("name") for p in data.get("team", [])}
    tag = to_quarter.replace(" ", "").lower()  # "q42026"

    company_src = [(e, False) for e in new.get("company_rocks", [])]
    company_src += [(e, True) for e in new.get("company_rocks_deferred", [])]
    for n, (entry, deferred) in enumerate(company_src, start=1):
        rid = f"cr_{tag}_{'def' if deferred else f'{n:02d}'}"
        if _rock_exists(data["company_rocks"], title=entry["title"], owner=entry["owner"],
                        quarter=entry.get("quarter", to_quarter), level="company"):
            plan["load_skipped"].append(entry["title"])
            continue
        rock = _build_rock(entry, rid, to_quarter, deferred=deferred)
        data["company_rocks"].append(rock)
        plan["loaded_company"].append({"title": rock["title"], "owner": rock["owner"],
                                       "rank": rock.get("rank"), "deferred": deferred})

    for n, entry in enumerate(new.get("individual_rocks", []), start=1):
        owner = entry["owner"]
        rid = f"r_{tag}_{n:02d}"
        bucket = data["rocks"].setdefault(owner, [])
        if _rock_exists(bucket, title=entry["title"], owner=owner,
                        quarter=entry.get("quarter", to_quarter), level="individual"):
            plan["load_skipped"].append(entry["title"])
            continue
        rock = _build_rock(entry, rid, to_quarter, deferred=False)
        bucket.append(rock)
        if owner not in team_names:
            data["team"].append({"name": owner, "role": entry.get("area", "")})
            team_names.add(owner)
        plan["loaded_individual"].append({"owner": owner, "title": rock["title"]})

    # Quarter registry + parked issues.
    data.setdefault("quarters", [])
    qinfo = dict(new.get("quarter") or {})
    qinfo.setdefault("id", to_quarter)
    qinfo.setdefault("label", to_quarter)
    qinfo.setdefault("closed", False)
    ids = {q.get("id") for q in data["quarters"]}
    if qinfo["id"] not in ids:
        data["quarters"].append(qinfo)
        plan["quarter_registered"] = qinfo["id"]
    if new.get("parked_issues"):
        data["parked_issues"] = [dict(p, quarter=to_quarter) for p in new["parked_issues"]]
        plan["parked_issues"] = len(data["parked_issues"])


# --- step 4: link CF successors + fixups -----------------------------------

def link_successors(data: dict[str, Any], from_quarter: str, to_quarter: str,
                    plan: dict[str, Any]) -> None:
    by_title = {}
    for owner_key, rock in iter_rocks(data):
        if rock.get("quarter") == to_quarter:
            by_title[(rock.get("title") or "").strip()] = rock
    for owner_key, rock in iter_rocks(data):
        if rock.get("quarter") != from_quarter or not rock.get("successor_title"):
            continue
        succ = by_title.get(rock["successor_title"].strip())
        if succ is None:
            plan["successor_missing"].append({"rock": rock.get("title"), "successor": rock["successor_title"]})
            continue
        if rock.get("successor_id") != succ.get("id"):
            rock["successor_id"] = succ["id"]
            succ.setdefault("predecessor_ids", [])
            if rock.get("id") not in succ["predecessor_ids"]:
                succ["predecessor_ids"].append(rock.get("id"))
            plan["successors_linked"].append({"from": rock.get("title"), "to": succ.get("title")})


def apply_fixups(data: dict[str, Any], fixups: list[dict[str, Any]], plan: dict[str, Any]) -> None:
    """Fixups are {"title", "owner", "set": {field: value}} — applied by title match."""
    for fx in fixups:
        if not fx.get("set"):
            continue
        rock = _find_rock(data, fx)
        if rock is None:
            plan["fixup_missing"].append(fx.get("title"))
            continue
        changed = {k: v for k, v in fx["set"].items() if rock.get(k) != v}
        if changed:
            rock.update(changed)
            plan["fixups_applied"].append({"title": rock.get("title"), "set": changed})


def close_quarter_registry(data: dict[str, Any], from_quarter: str, plan: dict[str, Any],
                           info: dict[str, Any] | None = None) -> None:
    """Mark the outgoing quarter closed in the registry (register it if missing).

    ``info`` may carry start/end/rock_session and an ``official_score``
    ({complete, total, source}) — the number the team agreed on, shown on the
    Scoreboard alongside the per-rock tally until the two reconcile.
    """
    data.setdefault("quarters", [])
    info = dict(info or {})
    info.pop("closed", None)
    for q in data["quarters"]:
        if q.get("id") == from_quarter:
            changed = False
            for k, v in info.items():
                if q.get(k) != v:
                    q[k] = v
                    changed = True
            if not q.get("closed"):
                q["closed"] = True
                q["closed_at"] = _now()
                changed = True
            if changed:
                plan["quarter_closed"] = from_quarter
            return
    entry = {"id": from_quarter, "label": from_quarter}
    entry.update(info)
    entry.update({"closed": True, "closed_at": _now()})
    data["quarters"].insert(0, entry)
    plan["quarter_closed"] = from_quarter


# --- orchestration ---------------------------------------------------------

def new_plan() -> dict[str, Any]:
    return {
        "closeout_stamped": [], "closeout_unchanged": [], "closeout_missing": [], "closeout_invalid": [],
        "todos_created": [], "todos_linked": [],
        "archived": [], "archive_skipped": [],
        "loaded_company": [], "loaded_individual": [], "load_skipped": [],
        "successors_linked": [], "successor_missing": [],
        "fixups_applied": [], "fixup_missing": [],
        "quarter_registered": None, "quarter_closed": None, "parked_issues": 0,
    }


def apply_rollover(data: dict[str, Any], migration: dict[str, Any],
                   new_rocks: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Apply the full rollover to ``data`` in place. Returns (data, plan)."""
    from_q = migration["from_quarter"]
    to_q = migration["to_quarter"]
    plan = new_plan()
    apply_fixups(data, migration.get("fixups", []), plan)          # e.g. missing quarter tag
    close_out_quarter(data, from_q, migration.get("closeout", []), plan)
    archive_quarter(data, from_q, plan)
    close_quarter_registry(data, from_q, plan, migration.get("from_quarter_info"))
    load_quarter(data, to_q, new_rocks, plan)
    link_successors(data, from_q, to_q, plan)
    return data, plan


def format_plan(plan: dict[str, Any]) -> str:
    L: list[str] = []
    L.append(f"FIXUPS: {len(plan['fixups_applied'])} applied, {len(plan['fixup_missing'])} missing")
    for f in plan["fixups_applied"]:
        L.append(f"   ~ {f['title']!r} set {f['set']}")
    for t in plan["fixup_missing"]:
        L.append(f"   ! MISSING rock for fixup: {t!r}")
    L.append(f"CLOSE-OUT: {len(plan['closeout_stamped'])} results stamped, "
             f"{len(plan['closeout_unchanged'])} unchanged, {len(plan['closeout_missing'])} missing, "
             f"{len(plan['closeout_invalid'])} invalid")
    for c in plan["closeout_stamped"]:
        L.append(f"   * {c['result']:<14} {c['title']!r}  ({c['owner']})")
    for t in plan["closeout_missing"]:
        L.append(f"   ! MISSING rock for close-out: {t!r}")
    for t in plan["closeout_invalid"]:
        L.append(f"   ! INVALID result {t['result']!r} on {t['title']!r}")
    L.append(f"TO-DOS: {len(plan['todos_created'])} created, {len(plan['todos_linked'])} linked to existing")
    for t in plan["todos_created"]:
        L.append(f"   + {t['todo_id']}  owner={t['owner']!r}  task={t['task']!r}  due={t['due']!r}")
    for t in plan["todos_linked"]:
        L.append(f"   = linked {t['todo_id']}  {t['task']!r}  <- rock {t['rock']!r}")
    L.append(f"ARCHIVE: {len(plan['archived'])} newly archived, {len(plan['archive_skipped'])} already archived")
    for a in plan["archived"]:
        L.append(f"   ~ {a['result'] or '-':<14} {a['title']!r}  ({a['owner']})")
    if plan["quarter_closed"]:
        L.append(f"QUARTER CLOSED: {plan['quarter_closed']}")
    L.append(f"LOAD: {len(plan['loaded_company'])} company + {len(plan['loaded_individual'])} individual "
             f"inserted, {len(plan['load_skipped'])} already present (skipped)")
    for r in plan["loaded_company"]:
        tag = " [DEFERRED]" if r["deferred"] else ""
        L.append(f"   + company #{r['rank'] or '-'} {r['title']!r}  ({r['owner']}){tag}")
    for r in plan["loaded_individual"]:
        L.append(f"   + indiv  [{r['owner']}] {r['title']!r}")
    if plan["quarter_registered"]:
        L.append(f"QUARTER REGISTERED: {plan['quarter_registered']}  (parked issues: {plan['parked_issues']})")
    L.append(f"SUCCESSORS: {len(plan['successors_linked'])} linked, {len(plan['successor_missing'])} missing")
    for s in plan["successors_linked"]:
        L.append(f"   -> {s['from']!r}  =>  {s['to']!r}")
    for s in plan["successor_missing"]:
        L.append(f"   ! MISSING successor {s['successor']!r} for {s['rock']!r}")
    return "\n".join(L)
