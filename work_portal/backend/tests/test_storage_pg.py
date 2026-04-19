"""Integration tests for PostgresStorage.

These are only run when TEST_DATABASE_URL is set. Otherwise they are skipped.
To run locally:
    TEST_DATABASE_URL=postgresql://... pytest tests/test_storage_pg.py
"""
import os
import uuid

import pytest

pytest.importorskip("psycopg")

from app.storage_pg import PostgresStorage

TEST_DSN = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not TEST_DSN,
    reason="TEST_DATABASE_URL not set — skipping Postgres integration tests",
)


@pytest.fixture
def pg_storage():
    store = PostgresStorage(dsn=TEST_DSN)
    # Wipe state between tests
    with store.pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE rocks_doc; TRUNCATE meetings;")
        conn.commit()
    yield store
    store.close()


def test_pg_rocks_round_trip(pg_storage):
    data = pg_storage.set_person_rocks("Chris", [{"id": "r1", "title": "t", "status": "incomplete"}])
    assert data["rocks"]["Chris"][0]["title"] == "t"
    assert pg_storage.load_rocks()["rocks"]["Chris"][0]["status"] == "incomplete"


def test_pg_company_rocks_round_trip(pg_storage):
    data = pg_storage.set_company_rocks([{"id": "c1", "title": "AUM", "status": "incomplete"}])
    assert data["company_rocks"][0]["title"] == "AUM"


def test_pg_toggle_rock(pg_storage):
    pg_storage.set_person_rocks("Chris", [{"id": "r1", "title": "t", "status": "incomplete"}])
    r = pg_storage.toggle_rock("r1")
    assert r["status"] == "complete"
    r2 = pg_storage.toggle_rock("r1")
    assert r2["status"] == "incomplete"


def test_pg_meetings_order_and_limit(pg_storage):
    pg_storage.save_meeting({"id": "a", "date": "2026-01-01", "title": "A"})
    pg_storage.save_meeting({"id": "b", "date": "2026-03-01", "title": "B"})
    pg_storage.save_meeting({"id": "c", "date": "2026-02-01", "title": "C"})
    ids = [m["id"] for m in pg_storage.list_meetings()]
    assert ids == ["b", "c", "a"]
    assert pg_storage.latest_meeting()["id"] == "b"
    assert len(pg_storage.list_meetings(limit=2)) == 2


def test_pg_meeting_upsert(pg_storage):
    pg_storage.save_meeting({"id": "m1", "date": "2026-01-01", "title": "first"})
    pg_storage.save_meeting({"id": "m1", "date": "2026-01-01", "title": "updated"})
    assert pg_storage.get_meeting("m1")["title"] == "updated"


def test_pg_meeting_not_found(pg_storage):
    assert pg_storage.get_meeting(str(uuid.uuid4())) is None
