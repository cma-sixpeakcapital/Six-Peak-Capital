"""Action items become to-dos automatically at ingest (Chris, 10/7/2026)."""
from app.ingest import IngestService
from app.todos import todos_from_action_items

from .conftest import FakeSummarizer


def _ingest(storage, meeting):
    svc = IngestService(storage=storage, summarizer=FakeSummarizer())
    return svc.ingest_webhook({"meeting": meeting})


def _meeting(**kw):
    m = {"id": "m1", "title": "Six Peak L10", "start_time": "2026-10-06T15:00:00Z",
         "summary": "s",
         "action_items": [{"text": "Chris Aiello will send the Reseda memo"},
                          {"owner": "Bob", "task": "Call Chase on the revolver", "due": "2026-10-20"},
                          {"owner": "Tom", "task": "Already handled", "completed": True}]}
    m.update(kw)
    return m


def test_ingest_creates_todos_for_open_items(storage):
    _ingest(storage, _meeting())
    todos = storage.list_todos()
    assert sorted(t["task"] for t in todos) == ["Call Chase on the revolver",
                                                "Chris Aiello will send the Reseda memo"]
    by_task = {t["task"]: t for t in todos}
    chase = by_task["Call Chase on the revolver"]
    assert chase["due"] == "2026-10-20"
    assert chase["owners"] == ["Bob Kennedy"]
    assert chase["source"]["type"] == "action_item"
    assert chase["source"]["meeting_id"] == "m1"
    assert chase["source"]["label"].startswith("from L10")
    memo = by_task["Chris Aiello will send the Reseda memo"]
    assert memo["owners"] == ["Chris Aiello"]
    assert memo.get("due_defaulted") is True
    m = storage.get_meeting("m1")
    linked = [a for a in m["action_items"] if a.get("todo_id")]
    assert len(linked) == 2  # completed item not converted
    assert len(m["action_items"]) == 3  # meeting keeps its list for the email


def test_reingest_does_not_duplicate(storage):
    _ingest(storage, _meeting())
    # A webhook re-send arrives with fresh item ids and no todo links.
    _ingest(storage, _meeting())
    assert len(storage.list_todos()) == 2
    m = storage.get_meeting("m1")
    assert sum(1 for a in m["action_items"] if a.get("todo_id")) == 2


def test_no_duplicate_after_todo_text_edited(storage):
    _ingest(storage, _meeting())
    t = next(t for t in storage.list_todos() if t["task"].startswith("Call Chase"))
    storage.update_todo(t["id"], {"task": "Call Chase + Wells on the revolver"})
    _ingest(storage, _meeting())
    assert len(storage.list_todos()) == 2


def test_rock_session_label():
    m = {"id": "r1", "kind": "rock_session", "date": "2026-12-01",
         "action_items": [{"id": "a", "task": "x"}]}
    data = {"todos": []}
    created = todos_from_action_items(m, data, [])
    assert created[0]["source"]["label"] == "from Rock Session 12/1"


def test_convert_existing_meeting_backfill(storage):
    storage.save_meeting({"id": "old", "date": "2026-09-29", "title": "L10",
                          "action_items": [{"id": "ai_1", "owner": "Grady", "task": "Pull comps"}]})
    m = storage.get_meeting("old")
    created = storage.convert_action_items(m)
    storage.save_meeting(m)
    assert [t["task"] for t in created] == ["Pull comps"]
    assert storage.convert_action_items(storage.get_meeting("old")) == []


def test_dashboard_has_no_action_items_card(client, storage):
    _ingest(storage, _meeting())
    html = client.get("/").get_data(as_text=True)
    assert "move-action-btn" not in html
    assert "Call Chase on the revolver" in html  # shows up as a to-do


def test_dashboard_section_order(client, storage):
    storage.save_meeting({"id": "m9", "date": "2026-10-06", "title": "L10",
                          "summary": "s", "topics": [{"topic": "Reseda", "notes": ["a"]}],
                          "action_items": []})
    storage.add_todo({"task": "x"})
    html = client.get("/").get_data(as_text=True)
    order = ['id="summary"', 'class="kpi-band', 'id="scorecard"', 'id="rocks"',
             'id="todos-divider"', 'id="todos"', 'id="history"']
    pos = [html.index(k) for k in order]
    assert pos == sorted(pos)
    assert "<details class=\"topic-bubble topic-collapsible\">" in html
