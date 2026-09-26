"""To-do lifecycle: dates, owners, drop, archive (Chris-approved plan, 9/26/2026).

Every to-do keeps, automatically:
  created_at      when it was made (UTC ISO)
  original_due    first due date it ever had (ISO date) - never changes
  due             current due date (ISO date)
  due_changes     [{from, to, at, by}] every later change
  completed_at    when it was checked off (cleared if un-checked)
  dropped_at / drop_reason / dropped_by   dropped instead of done
  archived_at     completed to-dos leave the list after the next L10 but are KEPT
  owners          list of names; ``owner`` stays as the joined display string

Rules agreed with Chris:
  1. No due date entered -> due 7 days after creation.
  2. Pre-existing to-dos with no due date -> 2026-10-06, flagged ``due_set_at_rollout``.
  3. Shared to-dos credit every named person.
  4. "Drop" replaces the x button; a true delete (mistakes) is still possible.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
SCHEMA = 2
DEFAULT_DUE_DAYS = 7
ROLLOUT_DUE = "2026-10-06"
SEPARATORS = re.compile(r"\s+and\s+|\s*&\s*|\s*/\s*|\s*,\s*|\s*\+\s*", re.I)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def et_date(value: Any) -> date | None:
    dt = parse_ts(value)
    return dt.astimezone(ET).date() if dt else None


def parse_due(value: Any, ref: date | None = None) -> date | None:
    """ISO (2026-10-06), M/D, M/D/YY or M/D/YYYY. Blank / 'TBD' -> None."""
    s = str(value or "").strip()
    if not s or s.upper() == "TBD":
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        pass
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})(?:/(\d{2}|\d{4}))?", s)
    if not m:
        return None
    mo, dy, yr = int(m.group(1)), int(m.group(2)), m.group(3)
    ref = ref or date.today()
    try:
        if yr:
            y = int(yr) + (2000 if len(yr) == 2 else 0)
            return date(y, mo, dy)
        d = date(ref.year, mo, dy)
    except ValueError:
        return None
    if d < ref - timedelta(days=180):
        d = date(ref.year + 1, mo, dy)
    return d


def resolve_owners(raw: Any, people: Iterable[str]) -> list[str]:
    """Free text or list -> list of names, mapped to the roster where possible.

    Full name, then unique first name, then unique last name. Anything that
    does not map (an outside party like "MRK") is kept as typed.
    """
    people = [p for p in people if p]
    tokens: list[str] = []
    for part in (raw if isinstance(raw, (list, tuple)) else [raw]):
        tokens += [t.strip() for t in SEPARATORS.split(str(part or "")) if t.strip()]
    out: list[str] = []
    for tok in tokens:
        low = tok.lower()
        match = next((p for p in people if p.lower() == low), None)
        if match is None:
            firsts = [p for p in people if p.split()[0].lower() == low]
            lasts = [p for p in people if p.split()[-1].lower() == low]
            match = firsts[0] if len(firsts) == 1 else (lasts[0] if len(lasts) == 1 else None)
        name = match or tok
        if name not in out:
            out.append(name)
    return out


def owner_list(todo: dict[str, Any], people: Iterable[str] = ()) -> list[str]:
    if todo.get("owners"):
        return list(todo["owners"])
    return resolve_owners(todo.get("owner"), people)


def is_dropped(t: dict[str, Any]) -> bool:
    return bool(t.get("dropped_at"))


def is_active(t: dict[str, Any]) -> bool:
    """Shown on the to-do list: not dropped and not archived."""
    return not is_dropped(t) and not t.get("archived_at")


def is_open(t: dict[str, Any]) -> bool:
    return is_active(t) and not t.get("completed")


def active_todos(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [t for t in (data.get("todos") or []) if is_active(t)]


def dropped_todos(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [t for t in (data.get("todos") or []) if is_dropped(t)]


def _set_owners(todo: dict[str, Any], owners: list[str]) -> None:
    todo["owners"] = owners
    todo["owner"] = " & ".join(owners)


def _owners_from(body: dict[str, Any], people: Iterable[str]) -> list[str] | None:
    """owners[] (+ owner_other) take priority over the legacy owner string."""
    if "owners" in body or "owner_other" in body:
        raw = list(body.get("owners") or [])
        if isinstance(body.get("owners"), str):
            raw = [body["owners"]]
        if (body.get("owner_other") or "").strip():
            raw.append(body["owner_other"])
        return resolve_owners(raw, people)
    if "owner" in body:
        return resolve_owners(body.get("owner"), people)
    return None


def init_new(todo: dict[str, Any], people: Iterable[str] = (), now: datetime | None = None) -> dict[str, Any]:
    """Stamp a brand-new to-do (any source) with the full schema."""
    now = now or now_utc()
    todo = dict(todo)
    todo.setdefault("created_at", now.isoformat())
    todo.setdefault("completed", False)
    _set_owners(todo, _owners_from(todo, people) or [])
    todo.pop("owner_other", None)
    created = et_date(todo["created_at"]) or now.astimezone(ET).date()
    raw_due = str(todo.get("due") or "").strip()
    due = parse_due(raw_due, created)
    if due is None:
        if raw_due and raw_due.upper() != "TBD":
            todo["due_note"] = raw_due  # e.g. "End of Jan 2026": kept, date defaulted
        due = created + timedelta(days=DEFAULT_DUE_DAYS)
        todo["due_defaulted"] = True
    todo["due"] = due.isoformat()
    todo["original_due"] = due.isoformat()
    todo["due_changes"] = []
    todo["completed_at"] = now.isoformat() if todo.get("completed") else None
    todo["schema"] = SCHEMA
    return todo


def apply_update(todo: dict[str, Any], body: dict[str, Any], people: Iterable[str] = (),
                 actor: str = "", now: datetime | None = None) -> dict[str, Any]:
    now = now or now_utc()
    if "task" in body and str(body["task"]).strip():
        todo["task"] = str(body["task"]).strip()
    owners = _owners_from(body, people)
    if owners is not None:
        _set_owners(todo, owners)
    if "due" in body:
        new = parse_due(body.get("due"), et_date(todo.get("created_at")))
        old = todo.get("due") or ""
        if new is not None and new.isoformat() != old:
            todo.setdefault("due_changes", []).append(
                {"from": old, "to": new.isoformat(), "at": now.isoformat(), "by": actor})
            todo["due"] = new.isoformat()
            if not todo.get("original_due"):
                todo["original_due"] = new.isoformat()
            todo.pop("due_defaulted", None)
    return todo


def toggle(todo: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    now = now or now_utc()
    todo["completed"] = not bool(todo.get("completed"))
    todo["completed_at"] = now.isoformat() if todo["completed"] else None
    return todo


def drop(todo: dict[str, Any], reason: str = "", actor: str = "", now: datetime | None = None) -> dict[str, Any]:
    now = now or now_utc()
    todo["dropped_at"] = now.isoformat()
    todo["drop_reason"] = (reason or "").strip()[:300]
    todo["dropped_by"] = actor
    return todo


def restore(todo: dict[str, Any]) -> dict[str, Any]:
    for k in ("dropped_at", "drop_reason", "dropped_by", "archived_at"):
        todo.pop(k, None)
    return todo


def archive_completed(data: dict[str, Any], now: datetime | None = None) -> int:
    """Replaces the old purge: completed to-dos leave the list but stay stored."""
    now = now or now_utc()
    n = 0
    for t in data.get("todos") or []:
        if t.get("completed") and not t.get("archived_at") and not is_dropped(t):
            t["archived_at"] = now.isoformat()
            n += 1
    return n


def migrate(data: dict[str, Any], people: Iterable[str],
            completions: dict[str, str] | None = None) -> int:
    """Bring pre-9/26 to-dos onto the schema. Idempotent; returns how many changed.

    ``completions`` maps todo id -> completed_at recovered from the change log.
    """
    completions = completions or {}
    people = list(people)
    n = 0
    for t in data.get("todos") or []:
        if t.get("schema") == SCHEMA:
            continue
        _set_owners(t, resolve_owners(t.get("owners") or t.get("owner"), people))
        created = et_date(t.get("created_at"))
        due = parse_due(t.get("due"), created)
        if due is None:
            if str(t.get("due") or "").strip():
                t["due_note"] = str(t["due"]).strip()
            t["due"] = ROLLOUT_DUE
            t["due_set_at_rollout"] = True
        else:
            t["due"] = due.isoformat()
        t.setdefault("original_due", t["due"])
        t.setdefault("due_changes", [])
        if t.get("completed"):
            t.setdefault("completed_at", completions.get(t.get("id")))
        else:
            t["completed_at"] = None
        t["schema"] = SCHEMA
        n += 1
    return n


def completions_from_audit(entries: Iterable[dict[str, Any]]) -> dict[str, str]:
    """Latest time each to-do flipped to completed=True, from audit_log rows."""
    out: dict[str, str] = {}
    for e in sorted(entries, key=lambda e: str(e.get("at") or e.get("created_at") or "")):
        at = e.get("at") or e.get("created_at")
        for ch in e.get("changes") or []:
            item = str(ch.get("item") or "")
            if not item.startswith("todo:"):
                continue
            after = ch.get("after") or {}
            if after.get("completed") is True and at:
                out[item[5:]] = str(at)
    return out
