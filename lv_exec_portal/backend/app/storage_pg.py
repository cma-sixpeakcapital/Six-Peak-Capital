"""Postgres-backed storage for the LV Executive portal.

Uses tables prefixed with `lv_` so the LV Exec portal can share a Neon
database with the L10 portal without colliding on table names.
Connection strategy: per-request psycopg.connect with 30s connect_timeout
(handles Neon free-tier cold-start). Same pattern as L10 storage_pg.
"""
import json
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterator

import psycopg
from psycopg.types.json import Json

from .storage import GOALS_SCHEMA_DEFAULT, STATUSES, _new_id

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS lv_doc (
    id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    data JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS lv_meetings (
    id TEXT PRIMARY KEY,
    date DATE NOT NULL,
    data JSONB NOT NULL,
    saved_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS lv_meetings_date_desc_idx ON lv_meetings (date DESC, saved_at DESC);

-- Follow-up email columns (added in v1 of automated recap feature).
-- followup_sent_at: NULL = not yet sent. Set on successful send (or dry-run draft).
-- followup_log:    JSONB record of {sent_at, recipients, dry_run, gmail_id, error}.
ALTER TABLE lv_meetings ADD COLUMN IF NOT EXISTS followup_sent_at TIMESTAMPTZ NULL;
ALTER TABLE lv_meetings ADD COLUMN IF NOT EXISTS followup_log JSONB NULL;
"""

CONNECT_TIMEOUT = 30


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

    # --- Doc ---

    def load_doc(self) -> dict[str, Any]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT data FROM lv_doc WHERE id = 1")
                row = cur.fetchone()
        if row is None:
            return json.loads(json.dumps(GOALS_SCHEMA_DEFAULT))
        data = row[0]
        data.setdefault("goals", [])
        data.setdefault("todos", [])
        return data

    def save_doc(self, data: dict[str, Any]) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO lv_doc (id, data, updated_at)
                    VALUES (1, %s, now())
                    ON CONFLICT (id) DO UPDATE
                        SET data = EXCLUDED.data, updated_at = now()
                    """,
                    (Json(data),),
                )
            conn.commit()

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

    def save_meeting(self, meeting: dict[str, Any]) -> dict[str, Any]:
        if "id" not in meeting or "date" not in meeting:
            raise ValueError("meeting requires 'id' and 'date'")
        meeting = dict(meeting)
        meeting.setdefault("saved_at", datetime.now(timezone.utc).isoformat())
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO lv_meetings (id, date, data)
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
        sql = "SELECT data FROM lv_meetings ORDER BY date DESC, saved_at DESC"
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
                cur.execute("SELECT data FROM lv_meetings WHERE id = %s", (meeting_id,))
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

    def list_meetings_pending_followup(
        self, *, min_age_hours: int = 24, max_age_days: int = 7
    ) -> list[dict[str, Any]]:
        sql = """
            SELECT data
            FROM lv_meetings
            WHERE followup_sent_at IS NULL
              AND (now() - (data->>'saved_at')::timestamptz) >= make_interval(hours => %s)
              AND (now() - (data->>'saved_at')::timestamptz) <= make_interval(days  => %s)
              AND coalesce(trim(data->>'summary'), '') <> ''
            ORDER BY data->>'saved_at' ASC
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (min_age_hours, max_age_days))
                return [row[0] for row in cur.fetchall()]

    def claim_followup(self, meeting_id: str) -> bool:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE lv_meetings
                       SET followup_sent_at = now()
                     WHERE id = %s AND followup_sent_at IS NULL
                    """,
                    (meeting_id,),
                )
                claimed = cur.rowcount == 1
            conn.commit()
        return claimed

    def release_followup(self, meeting_id: str) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE lv_meetings
                       SET followup_sent_at = NULL
                     WHERE id = %s
                       AND (followup_log IS NULL OR followup_log->>'error' IS NOT NULL)
                    """,
                    (meeting_id,),
                )
            conn.commit()

    def record_followup_log(self, meeting_id: str, log: dict[str, Any]) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE lv_meetings SET followup_log = %s WHERE id = %s",
                    (Json(log), meeting_id),
                )
            conn.commit()

    def close(self) -> None:
        pass
