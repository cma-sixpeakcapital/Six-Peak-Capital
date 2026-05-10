"""Tests for the IC Weekly storage layer (goals + todos + meetings + action items)."""
import pytest

from app.storage import Storage, bullet_split


# --- bullet_split ---

def test_bullet_split_empty():
    assert bullet_split("") == []
    assert bullet_split("   ") == []


def test_bullet_split_sentences():
    text = "Crew is shorthanded. Order materials by Friday. Review submittals next week."
    out = bullet_split(text)
    assert len(out) == 3
    assert out[0].startswith("Crew")


# --- Goals ---

def test_load_doc_default(storage: Storage):
    assert storage.load_doc() == {"goals": [], "todos": []}


def test_add_goal_assigns_id(storage: Storage):
    g = storage.add_goal({"title": "Hit 90% billable utilization"})
    assert g["id"].startswith("g_")
    assert g["status"] == "incomplete"
    assert storage.list_goals()[0]["title"] == "Hit 90% billable utilization"


def test_add_goal_validates_status(storage: Storage):
    with pytest.raises(ValueError):
        storage.add_goal({"title": "x", "status": "bogus"})


def test_set_goals_replaces_list(storage: Storage):
    storage.add_goal({"title": "first"})
    data = storage.set_goals([{"id": "g1", "title": "fresh", "status": "incomplete"}])
    assert len(data["goals"]) == 1 and data["goals"][0]["title"] == "fresh"


def test_toggle_goal(storage: Storage):
    g = storage.add_goal({"title": "t"})
    toggled = storage.toggle_goal(g["id"])
    assert toggled["status"] == "complete"
    again = storage.toggle_goal(g["id"])
    assert again["status"] == "incomplete"


def test_toggle_goal_missing(storage: Storage):
    assert storage.toggle_goal("nope") is None


def test_update_goal_patches_allowed_fields(storage: Storage):
    g = storage.add_goal({"title": "old"})
    out = storage.update_goal(g["id"], {"title": "new", "due": "2026-06-30", "notes": "n"})
    assert out["title"] == "new"
    assert out["due"] == "2026-06-30"
    assert out["status"] == "incomplete"  # status not in allowed list


def test_update_goal_ignores_unknown(storage: Storage):
    g = storage.add_goal({"title": "t"})
    out = storage.update_goal(g["id"], {"title": "new", "id": "hacked", "status": "complete"})
    assert out["id"] == g["id"]
    assert out["status"] == "incomplete"


def test_delete_goal(storage: Storage):
    g = storage.add_goal({"title": "t"})
    assert storage.delete_goal(g["id"]) is True
    assert storage.list_goals() == []


def test_delete_goal_missing(storage: Storage):
    assert storage.delete_goal("nope") is False


def test_move_goal_to_todos(storage: Storage):
    g = storage.add_goal({"title": "Hire ops manager", "due": "2026-08-15"})
    todo = storage.move_goal_to_todos(g["id"])
    assert todo["task"] == "Hire ops manager"
    assert todo["due"] == "2026-08-15"
    assert todo["source"]["type"] == "goal"
    assert storage.list_goals() == []
    assert any(t["id"] == todo["id"] for t in storage.list_todos())


def test_move_goal_missing(storage: Storage):
    assert storage.move_goal_to_todos("nope") is None


# --- Todos ---

def test_add_todo(storage: Storage):
    t = storage.add_todo({"owner": "Bob", "task": "Call vendor"})
    assert t["id"].startswith("td_")
    assert t["completed"] is False


def test_toggle_todo(storage: Storage):
    t = storage.add_todo({"task": "t"})
    assert storage.toggle_todo(t["id"])["completed"] is True


def test_delete_todo(storage: Storage):
    t = storage.add_todo({"task": "t"})
    assert storage.delete_todo(t["id"]) is True


def test_purge_completed_todos(storage: Storage):
    storage.add_todo({"task": "keep"})
    t = storage.add_todo({"task": "delete me"})
    storage.toggle_todo(t["id"])
    assert storage.purge_completed_todos() == 1
    assert len(storage.list_todos()) == 1
    assert storage.list_todos()[0]["task"] == "keep"


# --- Meetings + action items ---

def test_save_and_get_meeting(storage: Storage):
    storage.save_meeting({"id": "m1", "date": "2026-04-22", "title": "Six Peak IC Weekly"})
    m = storage.get_meeting("m1")
    assert m is not None and m["title"] == "Six Peak IC Weekly"


def test_meetings_sorted_desc(storage: Storage):
    storage.save_meeting({"id": "a", "date": "2026-01-01"})
    storage.save_meeting({"id": "b", "date": "2026-03-01"})
    storage.save_meeting({"id": "c", "date": "2026-02-01"})
    dates = [m["date"] for m in storage.list_meetings()]
    assert dates == ["2026-03-01", "2026-02-01", "2026-01-01"]


def test_toggle_action_item(storage: Storage):
    storage.save_meeting({
        "id": "m1", "date": "2026-04-22",
        "action_items": [{"id": "a1", "owner": "Chris", "task": "t"}],
    })
    item = storage.toggle_action_item("m1", "a1")
    assert item["completed"] is True


def test_move_action_item_to_todos(storage: Storage):
    storage.save_meeting({
        "id": "m1", "date": "2026-04-22", "title": "IC",
        "action_items": [
            {"id": "a1", "owner": "Chris", "task": "Send docs", "due": "2026-04-25"},
            {"id": "a2", "owner": "Bob", "task": "Other"},
        ],
    })
    todo = storage.move_action_item_to_todos("m1", "a1")
    assert todo["task"] == "Send docs"
    assert todo["source"]["meeting_id"] == "m1"
    m = storage.get_meeting("m1")
    assert len(m["action_items"]) == 1 and m["action_items"][0]["id"] == "a2"
