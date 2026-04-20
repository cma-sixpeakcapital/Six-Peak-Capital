import json
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROCKS_SCHEMA_DEFAULT: dict[str, Any] = {
    "team": [],
    "rocks": {},
    "company_rocks": [],
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
        with self.rocks_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)

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
        allowed = {"title", "notes", "due", "category", "link"}
        clean = {k: v for k, v in updates.items() if k in allowed}
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
        data.setdefault("todos", []).append(todo)
        self.save_rocks(data)
        return todo

    def list_todos(self) -> list[dict[str, Any]]:
        return list(self.load_rocks().get("todos", []) or [])

    def add_todo(self, todo: dict[str, Any]) -> dict[str, Any]:
        data = self.load_rocks()
        todo = dict(todo)
        todo.setdefault("id", _new_id("td"))
        todo.setdefault("completed", False)
        todo.setdefault("created_at", datetime.now(timezone.utc).isoformat())
        todo.setdefault("source", {"type": "manual"})
        data.setdefault("todos", []).append(todo)
        self.save_rocks(data)
        return todo

    def toggle_todo(self, todo_id: str) -> dict[str, Any] | None:
        data = self.load_rocks()
        for t in data.get("todos", []) or []:
            if t.get("id") == todo_id:
                t["completed"] = not bool(t.get("completed"))
                self.save_rocks(data)
                return t
        return None

    def delete_todo(self, todo_id: str) -> bool:
        data = self.load_rocks()
        before = len(data.get("todos", []) or [])
        data["todos"] = [t for t in (data.get("todos") or []) if t.get("id") != todo_id]
        if len(data["todos"]) == before:
            return False
        self.save_rocks(data)
        return True

    def purge_completed_todos(self) -> int:
        data = self.load_rocks()
        before = len(data.get("todos", []) or [])
        data["todos"] = [t for t in (data.get("todos") or []) if not t.get("completed")]
        removed = before - len(data["todos"])
        if removed:
            self.save_rocks(data)
        return removed

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
            "task": moved.get("task", ""),
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
        data.setdefault("todos", []).append(todo)
        self.save_rocks(data)
        return todo


def today_iso() -> str:
    return date.today().isoformat()
