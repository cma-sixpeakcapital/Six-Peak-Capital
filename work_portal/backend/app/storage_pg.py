"""Postgres-backed storage.

Schema:
  rocks_doc(id=1, data JSONB)          -- single row holding team/rocks/company_rocks
  meetings(id TEXT PK, date DATE, data JSONB, saved_at TIMESTAMPTZ)

Preserves the exact JSON shapes used by the JSON file storage, so the API
layer doesn't care which backend is active.
"""
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg.types.json import Json
from psycopg_pool import ConnectionPool

from .storage import ROCKS_SCHEMA_DEFAULT, STATUSES

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


@dataclass
class PostgresStorage:
    dsn: str
    pool: ConnectionPool = field(init=False)

    def __post_init__(self) -> None:
        self.pool = ConnectionPool(self.dsn, min_size=1, max_size=3, open=True)
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(SCHEMA_SQL)
            conn.commit()

    # --- Rocks ---

    def load_rocks(self) -> dict[str, Any]:
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT data FROM rocks_doc WHERE id = 1")
                row = cur.fetchone()
        if row is None:
            return json.loads(json.dumps(ROCKS_SCHEMA_DEFAULT))
        return row[0]

    def save_rocks(self, data: dict[str, Any]) -> None:
        with self.pool.connection() as conn:
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

    # --- Meetings ---

    def save_meeting(self, meeting: dict[str, Any]) -> dict[str, Any]:
        if "id" not in meeting or "date" not in meeting:
            raise ValueError("meeting requires 'id' and 'date'")
        meeting = dict(meeting)
        meeting.setdefault("saved_at", datetime.now(timezone.utc).isoformat())
        with self.pool.connection() as conn:
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
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return [row[0] for row in cur.fetchall()]

    def get_meeting(self, meeting_id: str) -> dict[str, Any] | None:
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT data FROM meetings WHERE id = %s", (meeting_id,))
                row = cur.fetchone()
        return row[0] if row else None

    def latest_meeting(self) -> dict[str, Any] | None:
        meetings = self.list_meetings(limit=1)
        return meetings[0] if meetings else None

    def close(self) -> None:
        self.pool.close()
