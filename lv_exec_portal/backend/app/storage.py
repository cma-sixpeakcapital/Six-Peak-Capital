"""JSON-file backend for the LV Executive portal.

Schema is simpler than the L10 portal:
- No individual rocks, no team list
- "goals" is a flat list of organization-level goals
- "todos" is the active to-do list (same shape as L10 todos)
- Meetings are stored separately, same shape as L10 meetings
"""
import json
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

GOALS_SCHEMA_DEFAULT: dict[str, Any] = {
    "goals": [],
    "todos": [],
}

STATUSES = {"complete", "incomplete"}


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def bullet_split(text: str) -> list[str]:
    """Split a paragraph into sentence-like bullets."""
    if not text or not text.strip():
        return []
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z(\"$\d])", text.strip())
    return [p.strip() for p in parts if p.strip()]


@dataclass
class Storage:
    data_dir: Path

    @property
    def goals_path(self) -> Path:
        return self.data_dir / "goals.json"

    @property
    def meetings_dir(self) -> Path:
        return self.data_dir / "meetings"

    # --- Goals doc (single dict on disk) ---

    def load_doc(self) -> dict[str, Any]:
        if not self.goals_path.exists():
            return json.loads(json.dumps(GOALS_SCHEMA_DEFAULT))
        with self.goals_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("goals", [])
        data.setdefault("todos", [])
        return data

    def save_doc(self, data: dict[str, Any]) -> None:
        self.goals_path.parent.mkdir(parents=True, exist_ok=True)
        with self.goals_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)

    # --- Goals ---

    def list_goals(self) -> list[dict[str, Any]]:
        return list(self.load_doc().get("goals", []) or [])

    def set_goals(self, goals: list[dict[str, Any]]) -> dict[str, Any]:
        data = self.load_doc()
        for goal in goals:
            status = goal.get("status", "incomplete")
            if status not in STATUSES:
                raise ValueError(f"invalid status: {status}")
        data["goals"] = goals
        self.save_doc(data)
        return data

    def add_goal(self, goal: dict[str, Any]) -> dict[str, Any]:
        data = self.load_doc()
        goal = dict(goal)
        goal.setdefault("id", _new_id("g"))
        goal.setdefault("status", "incomplete")
        if goal.get("status") not in STATUSES:
            raise ValueError(f"invalid status: {goal['status']}")
        data.setdefault("goals", []).append(goal)
        self.save_doc(data)
        return goal

    def toggle_goal(self, goal_id: str) -> dict[str, Any] | None:
        data = self.load_doc()
        for goal in data.get("goals", []) or []:
            if goal.get("id") == goal_id:
                goal["status"] = "incomplete" if goal.get("status") == "complete" else "complete"
                self.save_doc(data)
                return goal
        return None

    def update_goal(self, goal_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        allowed = {"title", "notes", "due", "link"}
        clean = {k: v for k, v in updates.items() if k in allowed}
        data = self.load_doc()
        for goal in data.get("goals", []) or []:
            if goal.get("id") == goal_id:
                goal.update(clean)
                self.save_doc(data)
                return goal
        return None

    def delete_goal(self, goal_id: str) -> bool:
        data = self.load_doc()
        before = len(data.get("goals", []) or [])
        data["goals"] = [g for g in (data.get("goals") or []) if g.get("id") != goal_id]
        if len(data["goals"]) == before:
            return False
        self.save_doc(data)
        return True

    def move_goal_to_todos(self, goal_id: str) -> dict[str, Any] | None:
        data = self.load_doc()
        removed: dict[str, Any] | None = None
        for i, goal in enumerate(data.get("goals", []) or []):
            if goal.get("id") == goal_id:
                removed = data["goals"].pop(i)
                break
        if removed is None:
            return None
        todo = {
            "id": _new_id("td"),
            "owner": "",
            "task": removed.get("title", ""),
            "due": removed.get("due", ""),
            "completed": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source": {"type": "goal", "goal_id": goal_id},
        }
        data.setdefault("todos", []).append(todo)
        self.save_doc(data)
        return todo

    # --- Todos ---

    def list_todos(self) -> list[dict[str, Any]]:
        return list(self.load_doc().get("todos", []) or [])

    def add_todo(self, todo: dict[str, Any]) -> dict[str, Any]:
        data = self.load_doc()
        todo = dict(todo)
        todo.setdefault("id", _new_id("td"))
        todo.setdefault("completed", False)
        todo.setdefault("created_at", datetime.now(timezone.utc).isoformat())
        todo.setdefault("source", {"type": "manual"})
        data.setdefault("todos", []).append(todo)
        self.save_doc(data)
        return todo

    def toggle_todo(self, todo_id: str) -> dict[str, Any] | None:
        data = self.load_doc()
        for t in data.get("todos", []) or []:
            if t.get("id") == todo_id:
                t["completed"] = not bool(t.get("completed"))
                self.save_doc(data)
                return t
        return None

    def delete_todo(self, todo_id: str) -> bool:
        data = self.load_doc()
        before = len(data.get("todos", []) or [])
        data["todos"] = [t for t in (data.get("todos") or []) if t.get("id") != todo_id]
        if len(data["todos"]) == before:
            return False
        self.save_doc(data)
        return True

    def purge_completed_todos(self) -> int:
        data = self.load_doc()
        before = len(data.get("todos", []) or [])
        data["todos"] = [t for t in (data.get("todos") or []) if not t.get("completed")]
        removed = before - len(data["todos"])
        if removed:
            self.save_doc(data)
        return removed

    # --- Meetings ---

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

    # --- Action items inside a meeting ---

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
        data = self.load_doc()
        data.setdefault("todos", []).append(todo)
        self.save_doc(data)
        return todo

    # --- follow-up email job ---------------------------------------------
    # File-backed parity with PostgresStorage. The "columns" live as
    # underscore-prefixed keys inside the meeting JSON so they don't
    # accidentally surface in the API or template (which use the real fields).

    def list_meetings_pending_followup(
        self, *, min_age_hours: int = 24, max_age_days: int = 7
    ) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc)
        out: list[dict[str, Any]] = []
        for m in self.list_meetings():
            if m.get("_followup_sent_at"):
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
        if log.get("error") or not log:
            meeting["_followup_sent_at"] = None
            self.save_meeting(meeting)

    def record_followup_log(self, meeting_id: str, log: dict[str, Any]) -> None:
        meeting = self.get_meeting(meeting_id)
        if meeting is None:
            return
        meeting["_followup_log"] = log
        self.save_meeting(meeting)


def today_iso() -> str:
    return date.today().isoformat()
