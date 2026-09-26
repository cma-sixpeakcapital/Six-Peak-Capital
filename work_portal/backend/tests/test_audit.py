"""Change log: every portal edit is recorded with before/after, the prior rocks
document is kept, and the restore script round-trips."""
import importlib.util
import os
from pathlib import Path

import pytest

from app import create_app
from app.audit import diff_items, index_doc
from app.storage import Storage

ROOT = Path(__file__).resolve().parents[3]


def seed(storage: Storage) -> None:
    storage.save_rocks({
        "team": [{"name": "Chris Aiello", "role": ""}, {"name": "Bob Kennedy", "role": ""}],
        "rocks": {"Chris Aiello": [{"id": "r_1", "title": "Reseda memo", "status": "incomplete", "due": "11/30"}]},
        "company_rocks": [{"id": "cr_1", "title": "Bonding", "status": "incomplete"}],
        "todos": [{"id": "td_1", "owner": "Bob Kennedy", "task": "Call Pat", "due": "", "completed": False}],
    })


@pytest.fixture
def app_and_storage(tmp_config):
    app = create_app(tmp_config)
    storage = app.config["STORAGE"]
    seed(storage)
    return app, storage


def test_diff_detects_added_removed_changed():
    before = {"rocks": {"A": [{"id": "r1", "title": "x", "due": "1"}]}, "todos": [{"id": "t1", "task": "a"}]}
    after = {"rocks": {"A": [{"id": "r1", "title": "x", "due": "2"}]}, "todos": [{"id": "t2", "task": "b"}]}
    ch = {c["item"]: c for c in diff_items(index_doc(before), index_doc(after))}
    assert ch["rock:r1"]["op"] == "changed" and ch["rock:r1"]["fields"] == ["due"]
    assert ch["rock:r1"]["before"] == {"due": "1"} and ch["rock:r1"]["after"] == {"due": "2"}
    assert ch["todo:t1"]["op"] == "removed" and ch["todo:t2"]["op"] == "added"


def test_edits_are_logged_with_actor_and_before_after(app_and_storage):
    app, storage = app_and_storage
    with app.test_client() as c:
        r = c.patch("/api/rocks/r_1", json={"due": "11/15"},
                    headers={"X-Actor": "Chris Aiello", "X-Forwarded-For": "203.0.113.9, 10.0.0.1"})
        assert r.status_code == 200
        c.post("/api/todos/td_1/toggle")
        c.delete("/api/rocks/cr_1")
    log = storage.list_audit()
    assert [e["action"] for e in log] == ["Delete rock", "Toggle to-do done", "Edit rock"]
    edit = log[-1]
    assert edit["actor"] == "Chris Aiello" and edit["ip"] == "203.0.113.9"
    ch = edit["changes"][0]
    assert ch["item"] == "rock:r_1" and ch["before"]["due"] == "11/30" and ch["after"]["due"] == "11/15"
    assert log[1]["actor"] == ""  # no name picked: recorded blank, edit still allowed
    deleted = log[0]["changes"][0]
    assert deleted["op"] == "removed" and deleted["before"]["title"] == "Bonding"


def test_failed_edits_and_reads_are_not_logged(app_and_storage):
    app, storage = app_and_storage
    with app.test_client() as c:
        c.patch("/api/rocks/nope", json={"due": "x"})  # 404
        c.get("/api/rocks")
    assert storage.list_audit() == []


def test_editing_stays_open_to_everyone(app_and_storage):
    app, _ = app_and_storage
    with app.test_client() as c:
        assert c.post("/api/todos", json={"task": "Anyone can add"}).status_code == 200


def test_changes_page_filters(app_and_storage):
    app, _ = app_and_storage
    with app.test_client() as c:
        c.patch("/api/rocks/r_1", json={"notes": "moved"}, headers={"X-Actor": "Bob Kennedy"})
        c.post("/api/todos/td_1/toggle", headers={"X-Actor": "Chris Aiello"})
        html = c.get("/changes").get_data(as_text=True)
        assert "Reseda memo" in html and "Bob Kennedy" in html
        only_bob = c.get("/changes?actor=bob").get_data(as_text=True)
        assert "Toggle to-do done" not in only_bob and "Edit rock" in only_bob


def test_history_kept_and_restore_round_trips(app_and_storage, capsys):
    app, storage = app_and_storage
    with app.test_client() as c:
        c.delete("/api/rocks/r_1")
    assert all(r["id"] != "r_1" for r in storage.load_rocks()["rocks"]["Chris Aiello"])
    hist = storage.list_rocks_history(limit=None)
    assert hist, "prior version must be kept on save"

    spec = importlib.util.spec_from_file_location("restore", ROOT / "scripts" / "restore_rocks_doc.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    newest = hist[0]["id"]  # the version the delete replaced
    assert mod.main(["--id", newest], storage=storage) == 0  # preview
    assert "would change" in capsys.readouterr().out
    assert all(r["id"] != "r_1" for r in storage.load_rocks()["rocks"]["Chris Aiello"])
    assert mod.main(["--id", newest, "--apply"], storage=storage) == 0
    assert any(r["id"] == "r_1" for r in storage.load_rocks()["rocks"]["Chris Aiello"])


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set")
def test_postgres_history_audit_and_snapshots():
    from datetime import datetime, timedelta, timezone

    import psycopg

    from app.storage_pg import PostgresStorage
    dsn = os.environ["TEST_DATABASE_URL"]
    with psycopg.connect(dsn) as conn:
        conn.execute("DROP TABLE IF EXISTS rocks_doc, meetings, rocks_doc_history, audit_log, scorecard_snapshots")
        conn.commit()
    st = PostgresStorage(dsn=dsn)
    st.save_rocks({"todos": [{"id": "a"}]})
    st.save_rocks({"todos": [{"id": "b"}]})
    hist = st.list_rocks_history()
    assert len(hist) == 1 and st.get_rocks_history(hist[0]["id"])["data"]["todos"][0]["id"] == "a"
    st.record_audit({"actor": "Bob Kennedy", "ip": "1.2.3.4", "action": "Edit rock",
                     "changes": [{"item": "rock:r1", "title": "Reseda"}], "status": 200})
    assert st.list_audit(actor="bob")[0]["action"] == "Edit rock"
    assert st.list_audit(text="reseda") and not st.list_audit(text="nothing-like-this")
    s1 = st.save_scorecard_snapshot("meeting", {"csv": {"metrics": "x"}}, "scheduled freeze")
    st.save_scorecard_snapshot("on_view", {"csv": {}}, "")
    latest_meeting = st.latest_scorecard_snapshot(kinds=("meeting",))
    assert latest_meeting["id"] == s1["id"] and latest_meeting["payload"]["csv"]["metrics"] == "x"
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    assert st.latest_scorecard_snapshot(since=future) is None
    assert st.latest_scorecard_snapshot()["kind"] == "on_view"
