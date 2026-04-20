"""Tests for new features: bullet_split, todos, action-item toggle/move, rock move, inline add."""
from app.storage import Storage, bullet_split


# -- bullet_split --

def test_bullet_split_empty():
    assert bullet_split("") == []
    assert bullet_split("   ") == []


def test_bullet_split_sentences():
    text = "The team reviewed closings. Third Street closes April 21. Bob will finalize EOS."
    out = bullet_split(text)
    assert len(out) == 3
    assert out[0].startswith("The team")
    assert out[2].endswith("EOS.")


def test_bullet_split_preserves_mid_sentence_punctuation():
    text = "We signed Genesis. $1.5M gap remains. Call Stain about 15%."
    out = bullet_split(text)
    assert "$1.5M gap remains." in out


# -- add_person_rock / add_company_rock --

def test_add_person_rock_assigns_id(storage: Storage):
    rock = storage.add_person_rock("Chris", {"title": "Ship it", "category": "Ops"})
    assert rock["id"].startswith("r_")
    assert rock["status"] == "incomplete"
    assert storage.load_rocks()["rocks"]["Chris"][0]["title"] == "Ship it"


def test_add_person_rock_adds_team_member(storage: Storage):
    storage.add_person_rock("Newbie", {"title": "Onboard"})
    names = [p["name"] for p in storage.load_rocks()["team"]]
    assert "Newbie" in names


def test_add_company_rock(storage: Storage):
    rock = storage.add_company_rock({"title": "Hit $10M AUM", "due": "2026-06-30"})
    assert rock["id"].startswith("cr_")
    assert storage.load_rocks()["company_rocks"][0]["title"] == "Hit $10M AUM"


# -- Todos --

def test_todos_default_empty(storage: Storage):
    assert storage.list_todos() == []


def test_add_todo(storage: Storage):
    todo = storage.add_todo({"owner": "Bob", "task": "Call lender"})
    assert todo["id"].startswith("td_")
    assert todo["completed"] is False
    assert storage.list_todos()[0]["task"] == "Call lender"


def test_toggle_todo(storage: Storage):
    t = storage.add_todo({"task": "t"})
    toggled = storage.toggle_todo(t["id"])
    assert toggled["completed"] is True
    again = storage.toggle_todo(t["id"])
    assert again["completed"] is False


def test_toggle_todo_missing(storage: Storage):
    assert storage.toggle_todo("nope") is None


def test_delete_todo(storage: Storage):
    t = storage.add_todo({"task": "t"})
    assert storage.delete_todo(t["id"]) is True
    assert storage.list_todos() == []


def test_delete_todo_missing(storage: Storage):
    assert storage.delete_todo("nope") is False


def test_purge_completed_todos(storage: Storage):
    storage.add_todo({"task": "keep"})
    t2 = storage.add_todo({"task": "delete me"})
    storage.toggle_todo(t2["id"])
    removed = storage.purge_completed_todos()
    assert removed == 1
    assert len(storage.list_todos()) == 1
    assert storage.list_todos()[0]["task"] == "keep"


# -- Action items inside a meeting --

def test_toggle_action_item(storage: Storage):
    storage.save_meeting({
        "id": "m1", "date": "2026-04-14",
        "action_items": [{"id": "a1", "owner": "Chris", "task": "t"}],
    })
    item = storage.toggle_action_item("m1", "a1")
    assert item["completed"] is True
    m = storage.get_meeting("m1")
    assert m["action_items"][0]["completed"] is True


def test_toggle_action_item_missing_meeting(storage: Storage):
    assert storage.toggle_action_item("nope", "a1") is None


def test_toggle_action_item_missing_action(storage: Storage):
    storage.save_meeting({"id": "m1", "date": "2026-04-14", "action_items": []})
    assert storage.toggle_action_item("m1", "nope") is None


def test_move_action_item_to_todos(storage: Storage):
    storage.save_meeting({
        "id": "m1", "date": "2026-04-14", "title": "L10",
        "action_items": [
            {"id": "a1", "owner": "Chris", "task": "Send docs", "due": "2026-04-15"},
            {"id": "a2", "owner": "Bob", "task": "Other"},
        ],
    })
    todo = storage.move_action_item_to_todos("m1", "a1")
    assert todo["task"] == "Send docs"
    assert todo["owner"] == "Chris"
    assert todo["source"]["type"] == "action_item"
    assert todo["source"]["meeting_id"] == "m1"
    # Action removed from meeting
    m = storage.get_meeting("m1")
    assert len(m["action_items"]) == 1
    assert m["action_items"][0]["id"] == "a2"
    # Todo present
    assert any(t["id"] == todo["id"] for t in storage.list_todos())


# -- Move rock to todos --

def test_move_rock_to_todos(storage: Storage):
    storage.set_person_rocks("Chris", [{"id": "r1", "title": "Close deal", "status": "incomplete"}])
    todo = storage.move_rock_to_todos("r1")
    assert todo["task"] == "Close deal"
    assert todo["source"]["type"] == "rock"
    assert todo["source"]["owner"] == "Chris"
    # Rock removed
    assert storage.load_rocks()["rocks"]["Chris"] == []


def test_move_company_rock_to_todos(storage: Storage):
    storage.set_company_rocks([{"id": "c1", "title": "Hit AUM", "status": "incomplete"}])
    todo = storage.move_rock_to_todos("c1")
    assert todo["source"]["type"] == "company_rock"
    assert storage.load_rocks()["company_rocks"] == []


def test_move_rock_missing(storage: Storage):
    assert storage.move_rock_to_todos("nope") is None


def test_delete_rock_person(storage: Storage):
    storage.set_person_rocks("Chris", [
        {"id": "r1", "title": "keep", "status": "incomplete"},
        {"id": "r2", "title": "delete me", "status": "incomplete"},
    ])
    assert storage.delete_rock("r2") is True
    remaining = storage.load_rocks()["rocks"]["Chris"]
    assert len(remaining) == 1 and remaining[0]["id"] == "r1"


def test_delete_company_rock(storage: Storage):
    storage.set_company_rocks([{"id": "c1", "title": "x", "status": "incomplete"}])
    assert storage.delete_rock("c1") is True
    assert storage.load_rocks()["company_rocks"] == []


def test_delete_rock_missing(storage: Storage):
    assert storage.delete_rock("nope") is False


def test_api_rock_delete(client, storage):
    storage.set_person_rocks("Chris", [{"id": "r1", "title": "t", "status": "incomplete"}])
    r = client.delete("/api/rocks/r1")
    assert r.status_code == 200
    assert storage.load_rocks()["rocks"]["Chris"] == []


def test_api_rock_delete_missing(client):
    assert client.delete("/api/rocks/nope").status_code == 404


def test_update_rock_patches_allowed_fields(storage: Storage):
    storage.set_person_rocks("Chris", [{"id": "r1", "title": "old", "status": "incomplete"}])
    updated = storage.update_rock("r1", {"title": "new", "due": "2026-05-01", "notes": "note"})
    assert updated["title"] == "new"
    assert updated["due"] == "2026-05-01"
    assert updated["notes"] == "note"
    # status preserved (not in allowed list for patch)
    assert updated["status"] == "incomplete"


def test_update_rock_ignores_unknown_fields(storage: Storage):
    storage.set_person_rocks("Chris", [{"id": "r1", "title": "t", "status": "incomplete"}])
    updated = storage.update_rock("r1", {"title": "new", "id": "hacked", "status": "complete"})
    assert updated["id"] == "r1"  # id untouched
    assert updated["status"] == "incomplete"  # status untouched
    assert updated["title"] == "new"


def test_update_company_rock(storage: Storage):
    storage.set_company_rocks([{"id": "c1", "title": "t", "status": "incomplete"}])
    updated = storage.update_rock("c1", {"title": "new", "due": "2026-06-30"})
    assert updated["title"] == "new"
    assert updated["due"] == "2026-06-30"


def test_update_rock_missing(storage: Storage):
    assert storage.update_rock("nope", {"title": "x"}) is None


def test_api_rock_update(client, storage):
    storage.set_person_rocks("Chris", [{"id": "r1", "title": "old", "status": "incomplete"}])
    r = client.patch("/api/rocks/r1", json={"title": "new", "due": "2026-05-01"})
    assert r.status_code == 200
    assert r.get_json()["title"] == "new"
    assert storage.load_rocks()["rocks"]["Chris"][0]["due"] == "2026-05-01"


def test_api_rock_update_missing(client):
    assert client.patch("/api/rocks/nope", json={"title": "x"}).status_code == 404


# --- Route tests ---

def test_api_todos_list(client, storage):
    storage.add_todo({"task": "one"})
    assert client.get("/api/todos").get_json()["todos"][0]["task"] == "one"


def test_api_add_todo_happy(client, storage):
    r = client.post("/api/todos", json={"task": "Do thing", "owner": "Chris"},
                    headers={"X-API-Key": "test-key"})
    assert r.status_code == 200
    assert r.get_json()["task"] == "Do thing"
    assert len(storage.list_todos()) == 1


def test_api_add_todo_rejects_empty_task(client):
    r = client.post("/api/todos", json={"task": "   "}, headers={"X-API-Key": "test-key"})
    assert r.status_code == 400


def test_api_toggle_todo(client, storage):
    t = storage.add_todo({"task": "t"})
    r = client.post(f"/api/todos/{t['id']}/toggle", headers={"X-API-Key": "test-key"})
    assert r.status_code == 200
    assert r.get_json()["completed"] is True


def test_api_delete_todo(client, storage):
    t = storage.add_todo({"task": "t"})
    r = client.delete(f"/api/todos/{t['id']}", headers={"X-API-Key": "test-key"})
    assert r.status_code == 200


def test_api_action_toggle(client, storage):
    storage.save_meeting({"id": "m1", "date": "2026-04-14",
                          "action_items": [{"id": "a1", "task": "x"}]})
    r = client.post("/api/action/m1/a1/toggle", headers={"X-API-Key": "test-key"})
    assert r.status_code == 200
    assert r.get_json()["completed"] is True


def test_api_action_move(client, storage):
    storage.save_meeting({"id": "m1", "date": "2026-04-14",
                          "action_items": [{"id": "a1", "owner": "Chris", "task": "move me"}]})
    r = client.post("/api/action/m1/a1/move", headers={"X-API-Key": "test-key"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["task"] == "move me"
    # Still in todos list
    assert any(t["id"] == body["id"] for t in storage.list_todos())


def test_api_rock_move(client, storage):
    storage.set_person_rocks("Chris", [{"id": "r1", "title": "do", "status": "incomplete"}])
    r = client.post("/api/rocks/r1/move", headers={"X-API-Key": "test-key"})
    assert r.status_code == 200
    assert r.get_json()["task"] == "do"


def test_api_add_person_rock(client, storage):
    r = client.post("/api/rocks/Chris/add",
                    json={"title": "Ship", "category": "Ops"},
                    headers={"X-API-Key": "test-key"})
    assert r.status_code == 200
    assert r.get_json()["title"] == "Ship"
    assert storage.load_rocks()["rocks"]["Chris"][0]["title"] == "Ship"


def test_api_add_company_rock(client, storage):
    r = client.post("/api/company_rocks/add",
                    json={"title": "$10M", "due": "2026-06-30"},
                    headers={"X-API-Key": "test-key"})
    assert r.status_code == 200


def test_api_add_person_rock_rejects_empty_title(client):
    r = client.post("/api/rocks/Chris/add", json={"title": ""},
                    headers={"X-API-Key": "test-key"})
    assert r.status_code == 400


def test_ingest_assigns_action_ids_and_purges_todos(client, storage):
    # Seed a completed todo to verify purge-on-ingest
    t = storage.add_todo({"task": "old"})
    storage.toggle_todo(t["id"])
    assert len(storage.list_todos()) == 1
    payload = {"meeting": {
        "id": "new1", "title": "L10 ingest test",
        "start_time": "2026-04-20T15:00:00Z",
        "summary": "s",
        "action_items": [{"owner": "Chris", "task": "t"}, {"owner": "Bob", "task": "u"}],
    }}
    r = client.post("/api/ingest/readai", json=payload, headers={"X-API-Key": "test-key"})
    assert r.status_code == 200
    m = storage.get_meeting("new1")
    for item in m["action_items"]:
        assert item["id"].startswith("ai_")
        assert item["completed"] is False
    # Completed todo should have been purged
    assert storage.list_todos() == []


def test_portal_renders_bulleted_summary(client, storage):
    storage.save_meeting({
        "id": "m1", "date": "2026-04-14", "title": "L10",
        "summary": "First sentence. Second sentence. Third sentence.",
        "action_items": [],
    })
    body = client.get("/").data.decode()
    assert "bullet-summary" in body
    assert "First sentence." in body
    assert "Second sentence." in body
