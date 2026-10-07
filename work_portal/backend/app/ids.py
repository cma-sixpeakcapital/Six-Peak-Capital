"""IDS issues list (Identify, Discuss, Solve) — Chris, 10/7/2026.

Issues that come up during the week or in the L10 live in the rocks document
under ``ids_issues`` (no schema migration; the change log diffs it like any
other top-level key). Each issue:

    id            "is_<hex>"
    title         one line naming the issue
    detail        optional context
    owners/owner  who raised / owns it (roster-resolved, like to-dos)
    status        "open" | "solved" | "dropped"
    raised_at     UTC ISO
    meeting_id    meeting it came from (Read.ai issues) or None
    source        {"type": "readai" | "manual", "label": "from L10 10/6"}
    resolution    what was decided (solved) or why it was dropped
    closed_at / closed_by
    todo_ids      to-dos created when it was solved

Read.ai issues arrive via ``PUT /api/meetings/<id>/issues`` from the weekly
scheduled Claude task (the portal has no Anthropic key). That upsert is
idempotent on meeting + title and never overrides a status someone set in
the portal.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

from . import todos as todo_lib

STATUSES = ("open", "solved", "dropped")
KEY = "ids_issues"
TITLE_MAX = 200


class IssueError(ValueError):
    """Bad input — surfaced as HTTP 400."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _norm(s: Any) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


def _new_id() -> str:
    return f"is_{uuid.uuid4().hex[:10]}"


def issues(data: dict[str, Any]) -> list[dict[str, Any]]:
    return data.setdefault(KEY, [])


def find(data: dict[str, Any], issue_id: str) -> dict[str, Any] | None:
    return next((i for i in data.get(KEY) or [] if i.get("id") == issue_id), None)


def _owners(body: dict[str, Any], people: Iterable[str]) -> list[str] | None:
    if "owners" in body or "owner_other" in body:
        raw = list(body.get("owners") or [])
        if (body.get("owner_other") or "").strip():
            raw.append(body["owner_other"])
        return todo_lib.resolve_owners(raw, people)
    if "owner" in body:
        return todo_lib.resolve_owners(body.get("owner"), people)
    return None


def _set_owners(issue: dict[str, Any], owners: list[str]) -> None:
    issue["owners"] = owners
    issue["owner"] = ", ".join(owners)


def _title(body: dict[str, Any]) -> str:
    title = re.sub(r"\s+", " ", str(body.get("title") or "")).strip()
    if not title:
        raise IssueError("'title' is required")
    return title[:TITLE_MAX]


def add(data: dict[str, Any], body: dict[str, Any], people: Iterable[str] = (),
        actor: str = "", now: datetime | None = None) -> dict[str, Any]:
    now = now or _now()
    issue = {
        "id": _new_id(),
        "title": _title(body),
        "detail": str(body.get("detail") or "").strip(),
        "status": "open",
        "raised_at": now.isoformat(),
        "meeting_id": None,
        "source": {"type": "manual", "label": "added in portal", "actor": actor or None},
        "resolution": "",
        "closed_at": None,
        "closed_by": None,
        "todo_ids": [],
    }
    _set_owners(issue, _owners(body, people) or [])
    issues(data).append(issue)
    return issue


def update(issue: dict[str, Any], body: dict[str, Any], people: Iterable[str] = ()) -> dict[str, Any]:
    if "title" in body:
        issue["title"] = _title(body)
    if "detail" in body:
        issue["detail"] = str(body.get("detail") or "").strip()
    owners = _owners(body, people)
    if owners is not None:
        _set_owners(issue, owners)
    return issue


def solve(data: dict[str, Any], issue: dict[str, Any], resolution: str,
          make_todo: bool = False, people: Iterable[str] = (), actor: str = "",
          now: datetime | None = None,
          new_todo_id: Callable[[], str] | None = None) -> dict[str, Any] | None:
    """Mark solved; optionally create a to-do from the resolution. Returns the to-do."""
    now = now or _now()
    resolution = str(resolution or "").strip()
    issue.update(status="solved", resolution=resolution,
                 closed_at=now.isoformat(), closed_by=actor or None)
    if not make_todo:
        return None
    todo = {
        "id": (new_todo_id or (lambda: f"td_{uuid.uuid4().hex[:10]}"))(),
        "owners": list(issue.get("owners") or []),
        "task": resolution or issue["title"],
        "due": "",
        "completed": False,
        "source": {"type": "ids_issue", "issue_id": issue["id"],
                   "label": "from IDS", "text": issue["title"]},
    }
    todo = todo_lib.init_new(todo, people, now)
    data.setdefault("todos", []).append(todo)
    issue.setdefault("todo_ids", []).append(todo["id"])
    return todo


def drop(issue: dict[str, Any], reason: str = "", actor: str = "",
         now: datetime | None = None) -> dict[str, Any]:
    now = now or _now()
    issue.update(status="dropped", resolution=str(reason or "").strip(),
                 closed_at=now.isoformat(), closed_by=actor or None)
    return issue


def reopen(issue: dict[str, Any]) -> dict[str, Any]:
    issue.update(status="open", closed_at=None, closed_by=None)
    return issue


def delete(data: dict[str, Any], issue_id: str) -> bool:
    lst = data.get(KEY) or []
    for i, it in enumerate(lst):
        if it.get("id") == issue_id:
            lst.pop(i)
            return True
    return False


def _label(meeting: dict[str, Any] | None) -> str:
    if not meeting:
        return "from Read.ai"
    return todo_lib._meeting_source_label(meeting)


def upsert_from_meeting(data: dict[str, Any], meeting: dict[str, Any],
                        items: list[dict[str, Any]], people: Iterable[str] = (),
                        actor: str = "", now: datetime | None = None) -> dict[str, list]:
    """Add issues extracted from a meeting. Idempotent on meeting + title.

    An existing issue is only refreshed (detail/owner) while still open and
    never has its status changed here — the portal is the source of truth
    once an issue exists. A new item may arrive already ``solved`` (decided in
    the meeting) or ``open``.
    """
    now = now or _now()
    if not isinstance(items, list):
        raise IssueError("'issues' must be a list")
    meeting_id = meeting.get("id")
    existing = {(_norm(i.get("title"))): i for i in data.get(KEY) or []
                if i.get("meeting_id") == meeting_id}
    added, refreshed = [], []
    for raw in items:
        if not isinstance(raw, dict):
            raise IssueError("each issue must be an object")
        title = _title(raw)
        status = raw.get("status") or "open"
        if status not in STATUSES:
            raise IssueError(f"status must be one of {STATUSES}")
        hit = existing.get(_norm(title))
        if hit:
            if hit.get("status") == "open":
                if raw.get("detail"):
                    hit["detail"] = str(raw["detail"]).strip()
                owners = _owners(raw, people)
                if owners:
                    _set_owners(hit, owners)
                refreshed.append(hit)
            continue
        issue = {
            "id": _new_id(),
            "title": title,
            "detail": str(raw.get("detail") or "").strip(),
            "status": status,
            "raised_at": (meeting.get("start_time") or meeting.get("date") or now.isoformat()),
            "meeting_id": meeting_id,
            "source": {"type": "readai", "label": _label(meeting), "actor": actor or None},
            "resolution": str(raw.get("resolution") or "").strip(),
            "closed_at": now.isoformat() if status != "open" else None,
            "closed_by": (actor or None) if status != "open" else None,
            "todo_ids": [t for t in (raw.get("todo_ids") or []) if isinstance(t, str)],
        }
        _set_owners(issue, _owners(raw, people) or [])
        issues(data).append(issue)
        existing[_norm(title)] = issue
        added.append(issue)
    return {"added": added, "refreshed": refreshed}


def view(data: dict[str, Any], since: str | None = None) -> dict[str, Any]:
    """Open issues oldest-first; closed ones (optionally since a date) newest-first."""
    all_ = list(data.get(KEY) or [])
    open_ = sorted([i for i in all_ if i.get("status") == "open"],
                   key=lambda i: str(i.get("raised_at") or ""))
    closed = [i for i in all_ if i.get("status") in ("solved", "dropped")]
    if since:
        closed = [i for i in closed if str(i.get("closed_at") or "")[:10] >= since]
    closed.sort(key=lambda i: str(i.get("closed_at") or ""), reverse=True)
    return {"open": open_, "closed": closed}
