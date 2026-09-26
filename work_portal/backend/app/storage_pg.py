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

from . import todos as _todos
from .rock_files import (
    FileArchivedError,
    apply_add_file,
    apply_remove_file,
    apply_update_file,
)
from .storage import RESULTS, ROCKS_SCHEMA_DEFAULT, STATUSES, _new_id, find_rock

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

-- Follow-up email columns (added in v1 of automated recap feature).
-- followup_sent_at: NULL = not yet sent. Set on successful send (or dry-run draft).
-- followup_log:    JSONB record of {sent_at, recipients, dry_run, gmail_id, error}.
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS followup_sent_at TIMESTAMPTZ NULL;
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS followup_log JSONB NULL;

-- Mid-cycle reminder columns (fires 3 days after each weekly L10 meeting —
-- halfway between meetings — as an automated nudge of open to-dos and rocks).
-- reminder_sent_at: NULL = not yet sent. Same atomic-claim pattern as follow-up.
-- reminder_log:    JSONB record of {sent_at, recipients, dry_run, gmail_id, error}.
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS reminder_sent_at TIMESTAMPTZ NULL;
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS reminder_log JSONB NULL;

-- Change log (Phase 1, 9/2026). rocks_doc_history keeps every replaced version
-- of the rocks document, including Render-shell edits that bypass the page, so
-- any change can be restored (scripts/restore_rocks_doc.py).
CREATE TABLE IF NOT EXISTS rocks_doc_history (
    id BIGSERIAL PRIMARY KEY,
    saved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    data JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS rocks_doc_history_saved_idx ON rocks_doc_history (saved_at DESC);

-- One row per edit made through the portal: who (self-reported), IP, browser,
-- and the before/after of every item that changed.
CREATE TABLE IF NOT EXISTS audit_log (
    id BIGSERIAL PRIMARY KEY,
    at TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor TEXT,
    ip TEXT,
    user_agent TEXT,
    method TEXT,
    path TEXT,
    action TEXT,
    status INTEGER,
    changes JSONB
);
CREATE INDEX IF NOT EXISTS audit_log_at_idx ON audit_log (at DESC);

-- Weekly Scorecard: raw CSV pulled from the published Sheet. kind is
-- on_view (page cache), manual (Refresh button) or meeting (Tuesday freeze).
CREATE TABLE IF NOT EXISTS scorecard_snapshots (
    id BIGSERIAL PRIMARY KEY,
    taken_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    kind TEXT NOT NULL,
    refreshed_by TEXT,
    payload JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS scorecard_snapshots_taken_idx ON scorecard_snapshots (taken_at DESC);
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
                # Keep the version being replaced (same transaction).
                cur.execute(
                    "INSERT INTO rocks_doc_history (data) SELECT data FROM rocks_doc WHERE id = 1"
                )
                # Bound storage on Neon: versions older than a year are dropped.
                cur.execute(
                    "DELETE FROM rocks_doc_history WHERE saved_at < now() - interval '365 days'"
                )
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
    # Parity with Storage.*_rock_file. Archived rocks are read-only for files.

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

    def list_meetings_pending_followup(
        self, *, min_age_hours: int = 24, max_age_days: int = 7,
        include_claimed: bool = False,
    ) -> list[dict[str, Any]]:
        """Meetings due for a follow-up email.

        Filters:
          - followup_sent_at IS NULL (not yet sent) — unless ``include_claimed``
          - data->>'saved_at' between max_age_days and min_age_hours ago
            (anchored on JSONB.saved_at so user clicks don't reset the clock)
          - summary is non-empty (don't send blank recaps)

        ``include_claimed=True`` drops the ``followup_sent_at IS NULL`` filter
        so a non-consuming preview can surface in-window meetings that are
        already blocked. Returns the meeting JSON dicts in saved_at ASC order
        so the oldest gets sent first if there's a backlog.
        """
        claim_clause = "" if include_claimed else "followup_sent_at IS NULL\n              AND "
        sql = f"""
            SELECT data
            FROM meetings
            WHERE {claim_clause}(now() - (data->>'saved_at')::timestamptz) >= make_interval(hours => %s)
              AND (now() - (data->>'saved_at')::timestamptz) <= make_interval(days  => %s)
              AND coalesce(trim(data->>'summary'), '') <> ''
            ORDER BY data->>'saved_at' ASC
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (min_age_hours, max_age_days))
                return [row[0] for row in cur.fetchall()]

    def claim_followup(self, meeting_id: str) -> bool:
        """Atomic claim. Returns True iff this caller now owns the send.

        Concurrent crons can both call this; only one gets True. The other
        gets False and skips the meeting.
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE meetings
                       SET followup_sent_at = now()
                     WHERE id = %s AND followup_sent_at IS NULL
                    """,
                    (meeting_id,),
                )
                claimed = cur.rowcount == 1
            conn.commit()
        return claimed

    def release_followup(self, meeting_id: str) -> None:
        """Undo a claim — used on error so the next cron retries.

        Only resets if no successful log was recorded; if record_followup_log
        wrote a success entry, we leave the claim in place (the send happened).
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE meetings
                       SET followup_sent_at = NULL
                     WHERE id = %s
                       AND (followup_log IS NULL OR followup_log->>'error' IS NOT NULL)
                    """,
                    (meeting_id,),
                )
            conn.commit()

    def record_followup_log(self, meeting_id: str, log: dict[str, Any]) -> None:
        """Persist send metadata so we have a durable trail beyond stdout."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE meetings SET followup_log = %s WHERE id = %s",
                    (Json(log), meeting_id),
                )
            conn.commit()

    # --- mid-cycle reminder job ------------------------------------------
    # Mirrors the follow-up methods but uses reminder_sent_at / reminder_log
    # columns. Anchors on the meeting's calendar DATE (not saved_at) so
    # Read AI re-ingests don't shift the schedule. Used by send_reminders.py.

    def list_meetings_pending_reminder(
        self, *, min_age_days: int = 3, max_age_days: int = 10,
        include_claimed: bool = False,
    ) -> list[dict[str, Any]]:
        """Meetings due for a mid-cycle reminder email.

        Filters:
          - reminder_sent_at IS NULL — unless ``include_claimed``
          - meeting date is between min_age_days and max_age_days ago
          - summary is non-empty

        ``include_claimed=True`` drops the ``reminder_sent_at IS NULL`` filter
        for non-consuming previews. Open-todos/rocks check happens in Python —
        those live in the rocks_doc table, not in the meeting row.
        """
        claim_clause = "" if include_claimed else "reminder_sent_at IS NULL\n              AND "
        sql = f"""
            SELECT data
            FROM meetings
            WHERE {claim_clause}(current_date - (data->>'date')::date) >= %s
              AND (current_date - (data->>'date')::date) <= %s
              AND coalesce(trim(data->>'summary'), '') <> ''
            ORDER BY (data->>'date')::date ASC
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (min_age_days, max_age_days))
                return [row[0] for row in cur.fetchall()]

    def claim_reminder(self, meeting_id: str) -> bool:
        """Atomic claim. Returns True iff this caller now owns the send."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE meetings
                       SET reminder_sent_at = now()
                     WHERE id = %s AND reminder_sent_at IS NULL
                    """,
                    (meeting_id,),
                )
                claimed = cur.rowcount == 1
            conn.commit()
        return claimed

    def release_reminder(self, meeting_id: str) -> None:
        """Undo a claim — used on error so the next cron retries."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE meetings
                       SET reminder_sent_at = NULL
                     WHERE id = %s
                       AND (reminder_log IS NULL OR reminder_log->>'error' IS NOT NULL)
                    """,
                    (meeting_id,),
                )
            conn.commit()

    def record_reminder_log(self, meeting_id: str, log: dict[str, Any]) -> None:
        """Persist reminder send metadata."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE meetings SET reminder_log = %s WHERE id = %s",
                    (Json(log), meeting_id),
                )
            conn.commit()

    # ---- rocks document history (restore) ---------------------------------
    def list_rocks_history(self, limit: int | None = 50, ascending: bool = False) -> list[dict[str, Any]]:
        order = "ASC" if ascending else "DESC"
        sql = f"SELECT id, saved_at FROM rocks_doc_history ORDER BY saved_at {order}, id {order}"
        params: tuple = ()
        if limit:
            sql += " LIMIT %s"
            params = (limit,)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        return [{"id": str(r[0]), "saved_at": r[1].isoformat()} for r in rows]

    def get_rocks_history(self, history_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id, saved_at, data FROM rocks_doc_history WHERE id = %s",
                            (int(history_id),))
                r = cur.fetchone()
        if r is None:
            return None
        return {"id": str(r[0]), "saved_at": r[1].isoformat(), "data": r[2]}

    # ---- change log --------------------------------------------------------
    def record_audit(self, entry: dict[str, Any]) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO audit_log (actor, ip, user_agent, method, path, action, status, changes)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (entry.get("actor"), entry.get("ip"), entry.get("user_agent"),
                     entry.get("method"), entry.get("path"), entry.get("action"),
                     entry.get("status"), Json(entry.get("changes") or [])),
                )
            conn.commit()

    def list_audit(self, limit: int = 200, actor: str | None = None, text: str | None = None,
                   since: str | None = None, until: str | None = None) -> list[dict[str, Any]]:
        where = []
        params: list[Any] = []
        if actor:
            where.append("actor ILIKE %s")
            params.append(f"%{actor}%")
        if text:
            where.append("(changes::text ILIKE %s OR action ILIKE %s)")
            params += [f"%{text}%", f"%{text}%"]
        if since:
            where.append("at >= %s")
            params.append(since)
        if until:
            where.append("at <= %s")
            params.append(until)
        sql = ("SELECT id, at, actor, ip, user_agent, method, path, action, status, changes "
               "FROM audit_log")
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY at DESC, id DESC LIMIT %s"
        params.append(limit)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        keys = ("id", "at", "actor", "ip", "user_agent", "method", "path", "action", "status", "changes")
        out = []
        for r in rows:
            d = dict(zip(keys, r))
            d["id"] = str(d["id"])
            d["at"] = d["at"].isoformat()
            out.append(d)
        return out

    # ---- scorecard snapshots ----------------------------------------------
    def save_scorecard_snapshot(self, kind: str, payload: dict[str, Any],
                                refreshed_by: str = "",
                                taken_at: datetime | None = None) -> dict[str, Any]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO scorecard_snapshots (kind, refreshed_by, payload, taken_at)
                    VALUES (%s, %s, %s, COALESCE(%s, now())) RETURNING id, taken_at
                    """,
                    (kind, refreshed_by, Json(payload), taken_at),
                )
                sid, taken = cur.fetchone()
                # Page-cache snapshots are only useful for a while; meeting and
                # manual snapshots are the record and are kept.
                cur.execute(
                    "DELETE FROM scorecard_snapshots WHERE kind = 'on_view' "
                    "AND taken_at < now() - interval '30 days'"
                )
            conn.commit()
        return {"id": str(sid), "taken_at": taken, "kind": kind,
                "refreshed_by": refreshed_by, "payload": payload}

    def latest_scorecard_snapshot(self, kinds: tuple[str, ...] | None = None,
                                  since: datetime | None = None) -> dict[str, Any] | None:
        where = []
        params: list[Any] = []
        if kinds:
            where.append("kind = ANY(%s)")
            params.append(list(kinds))
        if since is not None:
            where.append("taken_at >= %s")
            params.append(since)
        sql = "SELECT id, taken_at, kind, refreshed_by, payload FROM scorecard_snapshots"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY taken_at DESC, id DESC LIMIT 1"
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                r = cur.fetchone()
        if r is None:
            return None
        return {"id": str(r[0]), "taken_at": r[1], "kind": r[2], "refreshed_by": r[3] or "",
                "payload": r[4]}

    def close(self) -> None:
        # Nothing to close — connections are per-request.
        pass


def _roster() -> list[str]:
    from .scoring import ROSTER
    return list(ROSTER)
