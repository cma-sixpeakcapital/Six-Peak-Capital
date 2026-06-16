"""Q3 2026 rock rollover — pure, idempotent transform on the rocks_doc dict.

This module holds the *logic* for the one-time L10 rollover so it can be unit
tested without a database. ``scripts/migrate_q3_rocks.py`` is the thin CLI that
loads the live ``rocks_doc`` JSON, calls :func:`apply_migration`, prints the
plan, and (only with --apply) writes it back in one transaction.

The transform, in order (matches Claude_Code_Q3_rocks_implementation.md §C):
  1. Convert the 7 still-open old Individual rocks into to-dos owned by the
     individual (source tag ``from rock (Q2)``), then mark each source rock
     ``archived=true, converted=true``.
  2. Archive the 15 remaining old rocks (14 done + the open "AI Workflow"
     company rock) — ``archived=true`` only, no to-do.
  3. Load the Q3 set: 7 company + 1 deferred + 25 individual rocks.

Everything is keyed so a re-run is a no-op:
  * convert  → keyed on the source rock id (skip if a to-do already cites it)
  * archive  → skip rocks already archived
  * load     → skip a rock whose (level, owner, title, quarter) already exists

Status mapping (live DB uses complete/incomplete; Q3 JSON uses open/…):
  open → incomplete · in_progress → in_progress · deferred → incomplete (+flag)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "q3_2026"
Q3_DATA_PATH = DATA_DIR / "Q3_rocks_data.json"
Q3_MIGRATION_PATH = DATA_DIR / "Q3_rocks_migration.json"

OLD_QUARTER = "Q2 2026"
NEW_QUARTER = "Q3 2026"

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


# --- helpers ---------------------------------------------------------------

def _iter_all_rocks(data: dict[str, Any]):
    """Yield (location, list, index, rock) for every rock in the doc.

    location is ("company", None) or ("individual", owner_key).
    """
    for i, rock in enumerate(data.get("company_rocks", []) or []):
        yield ("company", None), data["company_rocks"], i, rock
    for owner, rocks in (data.get("rocks", {}) or {}).items():
        for i, rock in enumerate(rocks):
            yield ("individual", owner), rocks, i, rock


def _find_rock_by_title(data: dict[str, Any], title: str) -> dict[str, Any] | None:
    for _loc, _lst, _i, rock in _iter_all_rocks(data):
        if (rock.get("title") or "") == title:
            return rock
    return None


def _todo_cites_rock(data: dict[str, Any], rock_id: str) -> bool:
    for t in data.get("todos", []) or []:
        src = t.get("source") or {}
        if src.get("rock_id") == rock_id:
            return True
    return False


def _rock_exists(rocks: list[dict[str, Any]], *, title: str, owner: str,
                 quarter: str, level: str) -> bool:
    for r in rocks:
        if (r.get("title") == title and r.get("quarter") == quarter
                and r.get("level") == level and r.get("owner") == owner):
            return True
    return False


# --- step 1: convert open old individual rocks → to-dos --------------------

def convert_open_old_rocks(data: dict[str, Any], convert_list: list[dict[str, Any]],
                           plan: dict[str, Any]) -> None:
    data.setdefault("todos", [])
    for n, entry in enumerate(convert_list, start=1):
        title = entry["old_rock_title"]
        rock = _find_rock_by_title(data, title)
        if rock is None:
            plan["convert_missing"].append(title)
            continue
        rock_id = rock.get("id") or f"r_q2_{n:02d}"
        rock["id"] = rock_id
        # Idempotent: don't create a second to-do for the same source rock.
        if _todo_cites_rock(data, rock_id):
            plan["convert_skipped"].append({"title": title, "rock_id": rock_id})
        else:
            todo = {
                "id": f"td_q2conv_{n:02d}",
                "owner": entry["todo_owner"],
                "task": title,
                "detail": entry.get("detail", "") or rock.get("notes", "") or "",
                "due": entry.get("due", "") or rock.get("due", ""),
                "completed": False,
                "created_at": _now(),
                "source": {
                    "type": "rock",
                    "rock_id": rock_id,
                    "owner": entry["todo_owner"],
                    "quarter": OLD_QUARTER,
                    "label": "from rock (Q2)",
                },
            }
            data["todos"].append(todo)
            plan["converted"].append({
                "todo_id": todo["id"], "owner": todo["owner"],
                "task": todo["task"], "due": todo["due"], "source_rock_id": rock_id,
            })
        # Archive the source rock (retain, don't delete). Tag converted so the
        # "Past quarters" view and the archive count exclude it.
        rock["archived"] = True
        rock["converted"] = True
        rock["quarter"] = OLD_QUARTER


# --- step 2: archive remaining old rocks -----------------------------------

def archive_old_rocks(data: dict[str, Any], archive_list: list[dict[str, Any]],
                      plan: dict[str, Any]) -> None:
    for entry in archive_list:
        title = entry["title"]
        rock = _find_rock_by_title(data, title)
        if rock is None:
            plan["archive_missing"].append(title)
            continue
        if rock.get("archived"):
            plan["archive_skipped"].append(title)
            continue
        rock["archived"] = True
        rock["quarter"] = OLD_QUARTER
        plan["archived"].append({"title": title, "owner": entry.get("owner", "")})


# --- step 3: load the Q3 rock set ------------------------------------------

def _build_q3_rock(entry: dict[str, Any], rid: str, *, deferred: bool) -> dict[str, Any]:
    return {
        "id": rid,
        "level": entry["level"],
        "owner": entry["owner"],
        "title": entry["title"],
        "area": entry.get("area", ""),
        "priority": entry.get("priority"),
        "due": entry.get("due_date", ""),
        "due_date": entry.get("due_date", ""),
        "status": STATUS_MAP.get(entry.get("status", "open"), "incomplete"),
        "done_definition": entry.get("done_definition", ""),
        "dependencies": entry.get("dependencies", ""),
        "notes": entry.get("notes", ""),
        "quarter": entry.get("quarter", NEW_QUARTER),
        "archived": False,
        "deferred": deferred,
    }


def load_q3_rocks(data: dict[str, Any], q3: dict[str, Any], plan: dict[str, Any]) -> None:
    data.setdefault("company_rocks", [])
    data.setdefault("rocks", {})
    data.setdefault("team", [])
    team_names = {p.get("name") for p in data.get("team", [])}

    # Company (+ deferred) rocks
    company_src = [(e, False) for e in q3.get("company_rocks", [])]
    company_src += [(e, True) for e in q3.get("company_rocks_deferred", [])]
    for n, (entry, deferred) in enumerate(company_src, start=1):
        rid = f"cr_q3_{'def' if deferred else f'{n:02d}'}"
        if _rock_exists(data["company_rocks"], title=entry["title"],
                        owner=entry["owner"], quarter=entry.get("quarter", NEW_QUARTER),
                        level="company"):
            plan["load_skipped"].append(entry["title"])
            continue
        rock = _build_q3_rock(entry, rid, deferred=deferred)
        data["company_rocks"].append(rock)
        plan["loaded_company"].append({"title": rock["title"], "owner": rock["owner"],
                                       "deferred": deferred, "priority": rock["priority"]})

    # Individual rocks — grouped under the single-owner key (EOS standard).
    for n, entry in enumerate(q3.get("individual_rocks", []), start=1):
        owner = entry["owner"]
        rid = f"r_q3_{n:02d}"
        bucket = data["rocks"].setdefault(owner, [])
        if _rock_exists(bucket, title=entry["title"], owner=owner,
                        quarter=entry.get("quarter", NEW_QUARTER), level="individual"):
            plan["load_skipped"].append(entry["title"])
            continue
        rock = _build_q3_rock(entry, rid, deferred=False)
        bucket.append(rock)
        if owner not in team_names:
            data["team"].append({"name": owner, "role": entry.get("area", "")})
            team_names.add(owner)
        plan["loaded_individual"].append({"owner": owner, "title": rock["title"],
                                          "priority": rock["priority"], "status": rock["status"]})


# --- orchestration ---------------------------------------------------------

def _new_plan() -> dict[str, Any]:
    return {
        "converted": [], "convert_skipped": [], "convert_missing": [],
        "archived": [], "archive_skipped": [], "archive_missing": [],
        "loaded_company": [], "loaded_individual": [], "load_skipped": [],
    }


def apply_migration(data: dict[str, Any], q3: dict[str, Any],
                    mig: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Apply the full rollover to ``data`` in place. Returns (data, plan).

    Pure and idempotent — no DB, no I/O. Order matters: convert, then archive,
    then load Q3.
    """
    plan = _new_plan()
    convert_open_old_rocks(data, mig.get("convert_open_old_rocks_to_todos", []), plan)
    archive_old_rocks(data, mig.get("archive_done_old_rocks", []), plan)
    load_q3_rocks(data, q3, plan)
    return data, plan


def format_plan(plan: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"CONVERT → to-dos: {len(plan['converted'])} created, "
                 f"{len(plan['convert_skipped'])} already-converted (skipped)")
    for c in plan["converted"]:
        lines.append(f"   + to-do {c['todo_id']}  owner={c['owner']!r}  "
                     f"task={c['task']!r}  due={c['due']!r}  (archives rock {c['source_rock_id']})")
    for c in plan["convert_skipped"]:
        lines.append(f"   = skip (todo exists) rock {c['rock_id']}  {c['title']!r}")
    for t in plan["convert_missing"]:
        lines.append(f"   ! MISSING source rock for convert: {t!r}")

    lines.append(f"ARCHIVE: {len(plan['archived'])} newly archived, "
                 f"{len(plan['archive_skipped'])} already archived")
    for a in plan["archived"]:
        lines.append(f"   ~ archive {a['title']!r}  (owner {a['owner']!r})")
    for t in plan["archive_missing"]:
        lines.append(f"   ! MISSING rock to archive: {t!r}")

    lines.append(f"LOAD Q3: {len(plan['loaded_company'])} company "
                 f"+ {len(plan['loaded_individual'])} individual inserted, "
                 f"{len(plan['load_skipped'])} already present (skipped)")
    for r in plan["loaded_company"]:
        tag = " [DEFERRED/Q4]" if r["deferred"] else ""
        lines.append(f"   + company  {r['priority'] or '-':<6} {r['title']!r}  ({r['owner']}){tag}")
    for r in plan["loaded_individual"]:
        lines.append(f"   + indiv    {r['priority'] or '-':<6} [{r['owner']}] {r['title']!r}  ({r['status']})")
    return "\n".join(lines)
