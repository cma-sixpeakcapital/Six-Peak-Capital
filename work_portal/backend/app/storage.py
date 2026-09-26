import json
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from . import todos as _todos
from .rock_files import (
    FileArchivedError,
    apply_add_file,
    apply_remove_file,
    apply_update_file,
)

ROCKS_SCHEMA_DEFAULT: dict[str, Any] = {
    "team": [],
    "rocks": {},
    "company_rocks": [],
    "todos": [],
}

# "in_progress" added for Q3 2026 rocks (one rock — Schuyler's regulatory
# hurdles — is mid-flight). Existing rows use complete/incomplete; the toggle
# control still flips between those two, and in_progress renders as its own
# badge. Both Storage and PostgresStorage import this set.
STATUSES = {"complete", "incomplete", "in_progress"}

# Binary quarter-close results (see quarter_rollover.py / scoring.py).
RESULTS = {"complete", "carry_forward", "task", "killed", "deferred"}


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def bullet_split(text: str) -> list[str]:
    """Split a paragraph into sentence-like bullets."""
    if not text or not text.strip():
        return []
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z(\"$\d])", text.strip())
    return [p.strip() for p in parts if p.strip()]


def iter_all_rocks(data: dict[str, Any]):
    """Yield every rock dict (individual then company), all quarters."""
    for rocks in (data.get("rocks") or {}).values():
        for rock in rocks:
            yield rock
    for rock in data.get("company_rocks") or []:
        yield rock


def find_rock(data: dict[str, Any], rock_id: str) -> dict[str, Any] | None:
    """Locate a rock by id across individual and company collections."""
    for rock in iter_all_rocks(data):
        if rock.get("id") == rock_id:
            return rock
    return None


@dataclass
class Storage:
    data_dir: Path

    @property
    def rocks_path(self) -> Path:
        return self.data_dir / "rocks.json"

    @property
    def meetings_dir(self) -> Path:
        return self.data_dir / "meetings"

    def load_rocks(self) -> dict[str, Any]:
        if not self.rocks_path.exists():
            return json.loads(json.dumps(ROCKS_SCHEMA_DEFAULT))
        with self.rocks_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("todos", [])
        data.setdefault("company_rocks", [])
        return data

    def save_rocks(self, data: dict[str, Any]) -> None:
        self.rocks_path.parent.mkdir(parents=True, exist_ok=True)
        # Keep the version being replaced (change log / restore). Mirrors the
        # rocks_doc_history table in PostgresStorage.
        if self.rocks_path.exists():
            prior = json.loads(self.rocks_path.read_text(encoding="utf-8"))
            _append_jsonl(self.data_dir / "rocks_history.jsonl", {
                "id": _new_id("h"), "saved_at": _utcnow_iso(), "data": prior,
            })
        with self.rocks_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)

    # ---- rocks document history (restore) ---------------------------------
    def list_rocks_history(self, limit: int | None = 50, ascending: bool = False) -> list[dict[str, Any]]:
        rows = [{"id": r["id"], "saved_at": r["saved_at"]}
                for r in _read_jsonl(self.data_dir / "rocks_history.jsonl")]
        rows.sort(key=lambda r: r["saved_at"], reverse=not ascending)
        return rows[:limit] if limit else rows

    def get_rocks_history(self, history_id: str) -> dict[str, Any] | None:
        for r in _read_jsonl(self.data_dir / "rocks_history.jsonl"):
            if r["id"] == history_id:
                return r
        return None

    # ---- change log --------------------------------------------------------
    def record_audit(self, entry: dict[str, Any]) -> None:
        entry = dict(entry)
        entry.setdefault("id", _new_id("a"))
        entry.setdefault("at", _utcnow_iso())
        _append_jsonl(self.data_dir / "audit.jsonl", entry)

    def list_audit(self, limit: int = 200, actor: str | None = None, text: str | None = None,
                   since: str | None = None, until: str | None = None) -> list[dict[str, Any]]:
        rows = _read_jsonl(self.data_dir / "audit.jsonl")
        rows.sort(key=lambda r: r.get("at", ""), reverse=True)
        return [r for r in rows if _audit_match(r, actor, text, since, until)][:limit]

    # ---- scorecard snapshots ----------------------------------------------
    def save_scorecard_snapshot(self, kind: str, payload: dict[str, Any],
                                refreshed_by: str = "",
                                taken_at: datetime | None = None) -> dict[str, Any]:
        stamp = taken_at.isoformat() if taken_at else _utcnow_iso()
        row = {"id": _new_id("s"), "taken_at": stamp, "kind": kind,
               "refreshed_by": refreshed_by, "payload": payload}
        _append_jsonl(self.data_dir / "scorecard_snapshots.jsonl", row)
        return _snap_out(row)

    def latest_scorecard_snapshot(self, kinds: tuple[str, ...] | None = None,
                                  since: datetime | None = None) -> dict[str, Any] | None:
        best = None
        for r in _read_jsonl(self.data_dir / "scorecard_snapshots.jsonl"):
            if kinds and r["kind"] not in kinds:
                continue
            taken = datetime.fromisoformat(r["taken_at"])
            if since is not None and taken < since:
                continue
            if best is None or taken >= datetime.fromisoformat(best["taken_at"]):
                best = r
        return _snap_out(best) if best else None

    def set_person_rocks(self, person: str, rocks: list[dict[str, Any]]) -> dict[str, Any]:
        data = self.load_rocks()
        for rock in rocks:
            status = rock.get("status", "incomplete")
            if status not in STATUSES:
                raise ValueError(f"invalid status: {status}")
        data.setdefault("rocks", {})[person] = rocks
        people = {p["name"] for p in data.get("team", [])}
        if person not in people:
            data.setdefault("team", []).append({"name": person, "role": ""})
        self.save_rocks(data)
        return data

    def set_company_rocks(self, rocks: list[dict[str, Any]]) -> dict[str, Any]:
        data = self.load_rocks()
        for rock in rocks:
            status = rock.get("status", "incomplete")
            if status not in STATUSES:
                raise ValueError(f"invalid status: {status}")
        data["company_rocks"] = rocks
        self.save_rocks(data)
        return data

    def add_person_rock(self, person: str, rock: dict[str, Any]) -> dict[str, Any]:
        data = self.load_rocks()
        rock = dict(rock)
        rock.setdefault("id", _new_id("r"))
        rock.setdefault("status", "incomplete")
        if rock.get("status") not in STATUSES:
            raise ValueError(f"invalid status: {rock['status']}")
        data.setdefault("rocks", {}).setdefault(person, []).append(rock)
        people = {p["name"] for p in data.get("team", [])}
        if person not in people:
            data.setdefault("team", []).append({"name": person, "role": rock.get("category", "")})
        self.save_rocks(data)
        return rock

    def add_company_rock(self, rock: dict[str, Any]) -> dict[str, Any]:
        data = self.load_rocks()
        rock = dict(rock)
        rock.setdefault("id", _new_id("cr"))
        rock.setdefault("status", "incomplete")
        if rock.get("status") not in STATUSES:
            raise ValueError(f"invalid status: {rock['status']}")
        data.setdefault("company_rocks", []).append(rock)
        self.save_rocks(data)
        return rock

    def toggle_rock(self, rock_id: str) -> dict[str, Any] | None:
        data = self.load_rocks()
        for rocks in (data.get("rocks") or {}).values():
            for rock in rocks:
                if rock.get("id") == rock_id:
                    rock["status"] = "incomplete" if rock.get("status") == "complete" else "complete"
                    self.save_rocks(data)
                    return rock
        for rock in data.get("company_rocks") or []:
            if rock.get("id") == rock_id:
                rock["status"] = "incomplete" if rock.get("status") == "complete" else "complete"
                self.save_rocks(data)
                return rock
        return None

    def update_rock(self, rock_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        """Patch editable fields on a rock. Returns the updated rock or None if not found."""
        allowed = {
            "title", "notes", "due", "category", "link",
            "priority", "done_definition", "area", "dependencies",
            # quarter close-out fields (Scoreboard reads these on archived rocks)
            "result", "result_note", "root_cause", "controllable_action",
            "smart_statement", "review_status",
        }
        clean = {k: v for k, v in updates.items() if k in allowed}
        if "result" in clean and clean["result"] not in (None, "", *RESULTS):
            raise ValueError(f"invalid result: {clean['result']}")
        data = self.load_rocks()
        for rocks in (data.get("rocks") or {}).values():
            for rock in rocks:
                if rock.get("id") == rock_id:
                    rock.update(clean)
                    self.save_rocks(data)
                    return rock
        for rock in data.get("company_rocks") or []:
            if rock.get("id") == rock_id:
                rock.update(clean)
                self.save_rocks(data)
                return rock
        return None

    def delete_rock(self, rock_id: str) -> bool:
        """Remove a rock (person or company). Returns True if found and removed."""
        data = self.load_rocks()
        for rocks in (data.get("rocks") or {}).values():
            for i, rock in enumerate(rocks):
                if rock.get("id") == rock_id:
                    rocks.pop(i)
                    self.save_rocks(data)
                    return True
        for i, rock in enumerate(data.get("company_rocks") or []):
            if rock.get("id") == rock_id:
                data["company_rocks"].pop(i)
                self.save_rocks(data)
                return True
        return False

    # --- per-rock file links --------------------------------------------------
    # Archived rocks are read-only for files (chips still render, no writes).

    def add_rock_file(
        self, rock_id: str, url: str, label: str | None = None,
        added_by: str | None = None,
    ) -> dict[str, Any] | None:
        data = self.load_rocks()
        rock = find_rock(data, rock_id)
        if rock is None:
            return None
        if rock.get("archived"):
            raise FileArchivedError("cannot attach files to an archived rock")
        entry = apply_add_file(rock, url, label, added_by)
        self.save_rocks(data)
        return entry

    def update_rock_file(
        self, rock_id: str, file_id: str, url: str | None = None,
        label: str | None = None,
    ) -> dict[str, Any] | None:
        data = self.load_rocks()
        rock = find_rock(data, rock_id)
        if rock is None:
            return None
        if rock.get("archived"):
            raise FileArchivedError("cannot edit files on an archived rock")
        entry = apply_update_file(rock, file_id, url, label)
        if entry is None:
            return None
        self.save_rocks(data)
        return entry

    def remove_rock_file(self, rock_id: str, file_id: str) -> bool:
        data = self.load_rocks()
        rock = find_rock(data, rock_id)
        if rock is None:
            return False
        if rock.get("archived"):
            raise FileArchivedError("cannot remove files from an archived rock")
        if not apply_remove_file(rock, file_id):
            return False
        self.save_rocks(data)
        return True

    def move_rock_to_todos(self, rock_id: str) -> dict[str, Any] | None:
        data = self.load_rocks()
        removed: dict[str, Any] | None = None
        source_hint: dict[str, Any] | None = None
        for person, rocks in (data.get("rocks") or {}).items():
            for i, rock in enumerate(rocks):
                if rock.get("id") == rock_id:
                    removed = rocks.pop(i)
                    source_hint = {"type": "rock", "rock_id": rock_id, "owner": person}
                    break
            if removed:
                break
        if removed is None:
            for i, rock in enumerate(data.get("company_rocks") or []):
                if rock.get("id") == rock_id:
                    removed = data["company_rocks"].pop(i)
                    source_hint = {"type": "company_rock", "rock_id": rock_id}
                    break
        if removed is None:
            return None
        todo = {
            "id": _new_id("td"),
            "owner": (source_hint or {}).get("owner", ""),
            "task": removed.get("title", ""),
            "due": removed.get("due", ""),
            "completed": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source": source_hint or {"type": "rock"},
        }
        todo = _todos.init_new(todo, _roster())
        data.setdefault("todos", []).append(todo)
        self.save_rocks(data)
        return todo

    def list_todos(self) -> list[dict[str, Any]]:
        """To-dos on the list: not dropped, not archived (completed ones stay until the next L10)."""
        return _todos.active_todos(self.load_rocks())

    def list_all_todos(self) -> list[dict[str, Any]]:
        """Every to-do ever recorded, including archived and dropped (for metrics)."""
        return list(self.load_rocks().get("todos", []) or [])

    def add_todo(self, todo: dict[str, Any]) -> dict[str, Any]:
        data = self.load_rocks()
        todo = dict(todo)
        todo.setdefault("id", _new_id("td"))
        todo.setdefault("source", {"type": "manual"})
        todo = _todos.init_new(todo, _roster())
        data.setdefault("todos", []).append(todo)
        self.save_rocks(data)
        return todo

    def _edit_todo(self, todo_id: str, fn) -> dict[str, Any] | None:
        data = self.load_rocks()
        for t in data.get("todos", []) or []:
            if t.get("id") == todo_id:
                fn(t)
                self.save_rocks(data)
                return t
        return None

    def update_todo(self, todo_id: str, updates: dict[str, Any], actor: str = "") -> dict[str, Any] | None:
        """Patch owner(s) / task / due. Due changes are logged; original_due never moves."""
        return self._edit_todo(todo_id, lambda t: _todos.apply_update(t, updates, _roster(), actor))

    def toggle_todo(self, todo_id: str) -> dict[str, Any] | None:
        return self._edit_todo(todo_id, _todos.toggle)

    def drop_todo(self, todo_id: str, reason: str = "", actor: str = "") -> dict[str, Any] | None:
        return self._edit_todo(todo_id, lambda t: _todos.drop(t, reason, actor))

    def restore_todo(self, todo_id: str) -> dict[str, Any] | None:
        return self._edit_todo(todo_id, _todos.restore)

    def delete_todo(self, todo_id: str) -> bool:
        """Hard delete - for to-dos entered by mistake. Use drop_todo otherwise."""
        data = self.load_rocks()
        before = len(data.get("todos", []) or [])
        data["todos"] = [t for t in (data.get("todos") or []) if t.get("id") != todo_id]
        if len(data["todos"]) == before:
            return False
        self.save_rocks(data)
        return True

    def purge_completed_todos(self) -> int:
        """Called after each L10 is ingested. Completed to-dos leave the list but are
        ARCHIVED, not deleted, so completion history survives for the Hit Rate tab."""
        data = self.load_rocks()
        n = _todos.archive_completed(data)
        if n:
            self.save_rocks(data)
        return n

    def migrate_todos(self) -> int:
        """Bring older to-dos onto the dated schema (idempotent)."""
        data = self.load_rocks()
        if all(t.get("schema") == _todos.SCHEMA for t in data.get("todos") or []):
            return 0
        try:
            completions = _todos.completions_from_audit(self.list_audit(limit=5000, text="todo"))
        except Exception:  # audit is best-effort
            completions = {}
        n = _todos.migrate(data, _roster(), completions)
        if n:
            self.save_rocks(data)
        return n

    def save_meeting(self, meeting: dict[str, Any]) -> Path:
        if "id" not in meeting or "date" not in meeting:
            raise ValueError("meeting requires 'id' and 'date'")
        self.meetings_dir.mkdir(parents=True, exist_ok=True)
        path = self.meetings_dir / f"{meeting['id']}.json"
        meeting = dict(meeting)
        meeting.setdefault("saved_at", datetime.now(timezone.utc).isoformat())
        with path.open("w", encoding="utf-8") as f:
            json.dump(meeting, f, indent=2, sort_keys=True)
        return path

    def list_meetings(self, limit: int | None = None) -> list[dict[str, Any]]:
        if not self.meetings_dir.exists():
            return []
        meetings: list[dict[str, Any]] = []
        for path in self.meetings_dir.glob("*.json"):
            with path.open("r", encoding="utf-8") as f:
                meetings.append(json.load(f))
        meetings.sort(key=lambda m: m.get("date", ""), reverse=True)
        if limit is not None:
            meetings = meetings[:limit]
        return meetings

    def get_meeting(self, meeting_id: str) -> dict[str, Any] | None:
        path = self.meetings_dir / f"{meeting_id}.json"
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def latest_meeting(self) -> dict[str, Any] | None:
        meetings = self.list_meetings(limit=1)
        return meetings[0] if meetings else None

    def toggle_action_item(self, meeting_id: str, action_id: str) -> dict[str, Any] | None:
        meeting = self.get_meeting(meeting_id)
        if meeting is None:
            return None
        for item in meeting.get("action_items", []) or []:
            if item.get("id") == action_id:
                item["completed"] = not bool(item.get("completed"))
                self.save_meeting(meeting)
                return item
        return None

    def move_action_item_to_todos(self, meeting_id: str, action_id: str) -> dict[str, Any] | None:
        meeting = self.get_meeting(meeting_id)
        if meeting is None:
            return None
        items = meeting.get("action_items", []) or []
        moved: dict[str, Any] | None = None
        remaining: list[dict[str, Any]] = []
        for item in items:
            if moved is None and item.get("id") == action_id:
                moved = item
            else:
                remaining.append(item)
        if moved is None:
            return None
        meeting["action_items"] = remaining
        self.save_meeting(meeting)
        todo = {
            "id": _new_id("td"),
            "owner": moved.get("owner", ""),
            "task": moved.get("task") or moved.get("text") or "",
            "due": moved.get("due", ""),
            "completed": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source": {
                "type": "action_item",
                "meeting_id": meeting_id,
                "action_id": action_id,
                "meeting_title": meeting.get("title", ""),
            },
        }
        data = self.load_rocks()
        todo = _todos.init_new(todo, _roster())
        data.setdefault("todos", []).append(todo)
        self.save_rocks(data)
        return todo

    # --- follow-up email job ---------------------------------------------
    # File-backed parity with PostgresStorage. The "columns" live as
    # underscore-prefixed keys inside the meeting JSON so they don't
    # accidentally surface in the API or template (which use the real fields).

    def list_meetings_pending_followup(
        self, *, min_age_hours: int = 24, max_age_days: int = 7,
        include_claimed: bool = False,
    ) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc)
        out: list[dict[str, Any]] = []
        for m in self.list_meetings():
            if m.get("_followup_sent_at") and not include_claimed:
                continue
            saved_raw = m.get("saved_at")
            if not saved_raw:
                continue
            try:
                saved = datetime.fromisoformat(saved_raw)
            except (ValueError, TypeError):
                continue
            age = now - saved
            if age.total_seconds() < min_age_hours * 3600:
                continue
            if age.total_seconds() > max_age_days * 86400:
                continue
            if not (m.get("summary") or "").strip():
                continue
            out.append(m)
        out.sort(key=lambda m: m.get("saved_at", ""))
        return out

    def claim_followup(self, meeting_id: str) -> bool:
        meeting = self.get_meeting(meeting_id)
        if meeting is None or meeting.get("_followup_sent_at"):
            return False
        meeting["_followup_sent_at"] = datetime.now(timezone.utc).isoformat()
        self.save_meeting(meeting)
        return True

    def release_followup(self, meeting_id: str) -> None:
        meeting = self.get_meeting(meeting_id)
        if meeting is None:
            return
        log = meeting.get("_followup_log") or {}
        # Only release if the log doesn't show a successful send
        if log.get("error") or not log:
            meeting["_followup_sent_at"] = None
            self.save_meeting(meeting)

    def record_followup_log(self, meeting_id: str, log: dict[str, Any]) -> None:
        meeting = self.get_meeting(meeting_id)
        if meeting is None:
            return
        meeting["_followup_log"] = log
        self.save_meeting(meeting)

    # --- mid-cycle reminder job ------------------------------------------
    # File-backed parity for PostgresStorage's reminder_* methods.
    # Anchors on the meeting's calendar date (not saved_at) so re-ingests
    # don't shift the schedule.

    def list_meetings_pending_reminder(
        self, *, min_age_days: int = 3, max_age_days: int = 10,
        include_claimed: bool = False,
    ) -> list[dict[str, Any]]:
        today = date.today()
        out: list[dict[str, Any]] = []
        for m in self.list_meetings():
            if m.get("_reminder_sent_at") and not include_claimed:
                continue
            date_raw = m.get("date")
            if not date_raw:
                continue
            try:
                meeting_date = date.fromisoformat(str(date_raw))
            except (ValueError, TypeError):
                continue
            age_days = (today - meeting_date).days
            if age_days < min_age_days:
                continue
            if age_days > max_age_days:
                continue
            if not (m.get("summary") or "").strip():
                continue
            out.append(m)
        out.sort(key=lambda m: m.get("date", ""))
        return out

    def claim_reminder(self, meeting_id: str) -> bool:
        meeting = self.get_meeting(meeting_id)
        if meeting is None or meeting.get("_reminder_sent_at"):
            return False
        meeting["_reminder_sent_at"] = datetime.now(timezone.utc).isoformat()
        self.save_meeting(meeting)
        return True

    def release_reminder(self, meeting_id: str) -> None:
        meeting = self.get_meeting(meeting_id)
        if meeting is None:
            return
        log = meeting.get("_reminder_log") or {}
        if log.get("error") or not log:
            meeting["_reminder_sent_at"] = None
            self.save_meeting(meeting)

    def record_reminder_log(self, meeting_id: str, log: dict[str, Any]) -> None:
        meeting = self.get_meeting(meeting_id)
        if meeting is None:
            return
        meeting["_reminder_log"] = log
        self.save_meeting(meeting)


def today_iso() -> str:
    return date.today().isoformat()


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, default=str) + "\n")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _snap_out(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out["taken_at"] = datetime.fromisoformat(row["taken_at"])
    return out


def _audit_match(row: dict[str, Any], actor: str | None, text: str | None,
                 since: str | None, until: str | None) -> bool:
    """Shared filter for the change log (file backend; PG does the same in SQL)."""
    at = row.get("at", "")
    if since and at < since:
        return False
    if until and at > until:
        return False
    if actor and actor.lower() not in (row.get("actor") or "").lower():
        return False
    if text:
        blob = json.dumps(row.get("changes") or [], default=str).lower() + " " + (row.get("action") or "").lower()
        if text.lower() not in blob:
            return False
    return True


def _roster() -> list[str]:
    from .scoring import ROSTER
    return list(ROSTER)
