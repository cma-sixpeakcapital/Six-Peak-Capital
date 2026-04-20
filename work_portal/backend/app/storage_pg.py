"""Postgres-backed storage (schema: rocks_doc + meetings, both JSONB).

Connection strategy: open a fresh psycopg.connect per request with a
generous connect_timeout. ConnectionPool kept timing out on Neon free-
tier cold starts even with check_connection enabled. For a low-traffic
dashboard (<<1 RPS) direct connections are reliable and simple.
"""
import json
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterator

import psycopg
from psycopg.types.json import Json

from .storage import ROCKS_SCHEMA_DEFAULT, STATUSES, _new_id

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS rocks_doc (
    id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    data JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS meetings (
    id TEXT PRIMARY KEY,
    date DATE NOT NULL,
    data JSONB NOT NULL,
    saved_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS meetings_date_desc_idx ON meetings (date DESC, saved_at DESC);
"""

CONNECT_TIMEOUT = 30  # seconds — covers Neon cold-start from idle


@dataclass
class PostgresStorage:
    dsn: str

    def __post_init__(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(SCHEMA_SQL)
            conn.commit()

    @contextmanager
    def _connect(self) -> Iterator[psycopg.Connection]:
        conn = psycopg.connect(self.dsn, connect_timeout=CONNECT_TIMEOUT)
        try:
            yield conn
        finally:
            conn.close()

    def load_rocks(self) -> dict[str, Any]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT data FROM rocks_doc WHERE id = 1")
                row = cur.fetchone()
        if row is None:
            return json.loads(json.dumps(ROCKS_SCHEMA_DEFAULT))
        data = row[0]
        data.setdefault("todos", [])
        data.setdefault("company_rocks", [])
        return data

    def save_rocks(self, data: dict[str, Any]) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO rocks_doc (id, data, updated_at)
                    VALUES (1, %s, now())
                    ON CONFLICT (id) DO UPDATE
                        SET data = EXCLUDED.data, updated_at = now()
                    """,
                    (Json(data),),
                )
            conn.commit()

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

    def save_meeting(self, meeting: dict[str, Any]) -> dict[str, Any]:
        if "id" not in meeting or "date" not in meeting:
            raise ValueError("meeting requires 'id' and 'date'")
        meeting = dict(meeting)
        meeting.setdefault("saved_at", datetime.now(timezone.utc).isoformat())
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO meetings (id, date, data)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (id) DO UPDATE
                        SET date = EXCLUDED.date,
                            data = EXCLUDED.data,
                            saved_at = now()
                    """,
                    (meeting["id"], meeting["date"], Json(meeting)),
                )
            conn.commit()
        return meeting

    def list_meetings(self, limit: int | None = None) -> list[dict[str, Any]]:
        sql = "SELECT data FROM meetings ORDER BY date DESC, saved_at DESC"
        params: tuple[Any, ...] = ()
        if limit is not None:
            sql += " LIMIT %s"
            params = (limit,)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return [row[0] for row in cur.fetchall()]

    def get_meeting(self, meeting_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT data FROM meetings WHERE id = %s", (meeting_id,))
                row = cur.fetchone()
        return row[0] if row else None

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

    def close(self) -> None:
        # Nothing to close — connections are per-request.
        pass
