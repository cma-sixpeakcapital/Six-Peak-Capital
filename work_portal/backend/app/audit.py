"""Change log for every edit made through the portal.

Editing stays open to anyone with the link (Chris, 9/25/2026). This module makes
every edit auditable without changing who can edit:

- before each write request (POST/PUT/PATCH/DELETE under /api/, except the
  API-key job endpoints) the rocks document - and the meeting, for action-item
  edits - is loaded;
- after a successful response it is loaded again and diffed item by item
  (rocks, company rocks, to-dos, meeting action items, other top-level keys);
- one audit row is written: time, action, self-reported name (X-Actor header,
  set by the "You are" picker), IP, browser, and before/after per changed item.

The self-reported name is NOT verified. Any failure here is logged and swallowed
so auditing can never break an edit.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from flask import Flask, g, request

log = logging.getLogger(__name__)

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
# API-key jobs are automation, not edits; they have their own logs.
SKIP_PREFIXES = ("/api/jobs/", "/api/ingest/", "/api/refresh")
ACTION_RE = re.compile(r"^/api/action/([^/]+)/")

ACTION_LABELS = {
    "api_update_rocks": "Replace person's rocks",
    "api_toggle_rock": "Toggle rock complete",
    "api_rock_update": "Edit rock",
    "api_rock_delete": "Delete rock",
    "api_rock_move": "Move rock to To-Dos",
    "api_rock_file_add": "Add rock file link",
    "api_rock_file_update": "Edit rock file link",
    "api_rock_file_delete": "Remove rock file link",
    "api_rock_add": "Add rock",
    "api_update_company_rocks": "Replace company rocks",
    "api_company_rock_add": "Add company rock",
    "api_todos_add": "Add to-do",
    "api_todo_update": "Edit to-do",
    "api_todo_toggle": "Toggle to-do done",
    "api_todo_delete": "Delete to-do",
    "api_action_toggle": "Toggle meeting action item",
    "api_action_move": "Move action item to To-Dos",
    "api_scorecard_refresh": "Refresh scorecard from Sheet",
    "api_meeting_set_topics": "Set meeting summary topics",
}


def _canon(x: Any) -> str:
    return json.dumps(x, sort_keys=True, default=str)


def _title(item: dict[str, Any] | None) -> str:
    if not item:
        return ""
    return str(item.get("title") or item.get("task") or item.get("text") or item.get("id") or "")


def index_doc(doc: dict[str, Any]) -> dict[str, tuple[str, dict[str, Any]]]:
    """Map every addressable item in the rocks document to a stable key."""
    out: dict[str, tuple[str, dict[str, Any]]] = {}
    for person, rocks in (doc.get("rocks") or {}).items():
        for r in rocks or []:
            key = f"rock:{r.get('id') or person + ':' + _title(r)}"
            out[key] = ("rock", {**r, "_owner": person})
    for r in doc.get("company_rocks") or []:
        out[f"rock:{r.get('id') or _title(r)}"] = ("company_rock", r)
    for t in doc.get("todos") or []:
        out[f"todo:{t.get('id') or _title(t)}"] = ("todo", t)
    for k, v in doc.items():
        if k not in {"rocks", "company_rocks", "todos"}:
            out[f"doc:{k}"] = ("document", {"value": v})
    return out


def diff_items(before: dict[str, tuple[str, dict[str, Any]]],
               after: dict[str, tuple[str, dict[str, Any]]]) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for key in sorted(set(before) | set(after)):
        b = before.get(key)
        a = after.get(key)
        if b and not a:
            changes.append({"item": key, "type": b[0], "op": "removed", "title": _title(b[1]),
                            "before": b[1], "after": None})
        elif a and not b:
            changes.append({"item": key, "type": a[0], "op": "added", "title": _title(a[1]),
                            "before": None, "after": a[1]})
        elif _canon(a[1]) != _canon(b[1]):
            bf, af = b[1], a[1]
            fields = sorted(k for k in set(bf) | set(af) if _canon(bf.get(k)) != _canon(af.get(k)))
            changes.append({"item": key, "type": a[0], "op": "changed", "title": _title(af),
                            "fields": fields,
                            "before": {k: bf.get(k) for k in fields},
                            "after": {k: af.get(k) for k in fields}})
    return changes


def diff_meeting(before: dict[str, Any] | None, after: dict[str, Any] | None) -> list[dict[str, Any]]:
    def idx(m: dict[str, Any] | None) -> dict[str, tuple[str, dict[str, Any]]]:
        if not m:
            return {}
        return {f"action:{m.get('id')}:{a.get('id')}": ("action_item", a)
                for a in m.get("action_items") or []}
    return diff_items(idx(before), idx(after))


def client_ip() -> str:
    fwd = request.headers.get("X-Forwarded-For", "")
    return (fwd.split(",")[0].strip() if fwd else request.remote_addr) or ""


def actor_name() -> str:
    return (request.headers.get("X-Actor") or "").strip()[:60]


def _should_audit() -> bool:
    return (request.method in WRITE_METHODS and request.path.startswith("/api/")
            and not request.path.startswith(SKIP_PREFIXES))


def register_audit(app: Flask, get_storage) -> None:
    @app.before_request
    def _audit_before() -> None:
        if not _should_audit():
            return
        try:
            storage = get_storage()
            g.audit_doc_before = json.loads(_canon(storage.load_rocks()))
            m = ACTION_RE.match(request.path)
            if m:
                g.audit_meeting_id = m.group(1)
                g.audit_meeting_before = json.loads(_canon(storage.get_meeting(m.group(1))))
        except Exception:  # pragma: no cover - never block an edit
            log.exception("audit: could not snapshot before state")

    @app.after_request
    def _audit_after(response):
        if not _should_audit() or not (200 <= response.status_code < 300):
            return response
        try:
            storage = get_storage()
            changes: list[dict[str, Any]] = []
            before = getattr(g, "audit_doc_before", None)
            if before is not None:
                changes += diff_items(index_doc(before), index_doc(storage.load_rocks()))
            mid = getattr(g, "audit_meeting_id", None)
            if mid:
                changes += diff_meeting(getattr(g, "audit_meeting_before", None),
                                        storage.get_meeting(mid))
            storage.record_audit({
                "actor": actor_name(),
                "ip": client_ip(),
                "user_agent": (request.headers.get("User-Agent") or "")[:200],
                "method": request.method,
                "path": request.path,
                "action": ACTION_LABELS.get(request.endpoint or "", request.endpoint or request.path),
                "status": response.status_code,
                "changes": json.loads(_canon(changes)),
            })
        except Exception:  # pragma: no cover
            log.exception("audit: could not record change")
        return response
