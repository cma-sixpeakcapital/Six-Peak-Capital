"""Route-level smoke tests for the LV Exec portal."""
from app.storage import Storage


def test_health(client):
    assert client.get("/health").get_json() == {"status": "ok"}


def test_portal_renders_empty(client):
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "LV Bi-Weekly Executive" in body
    assert "No meetings ingested yet" in body


def test_portal_renders_with_meeting_and_goals(client, storage: Storage):
    storage.add_goal({"title": "Hit 90% utilization", "due": "2026-06-30"})
    storage.save_meeting({
        "id": "m1", "date": "2026-04-22", "title": "LV Exec Apr 22",
        "summary": "First. Second.", "action_items": [], "files": [],
    })
    body = client.get("/").data.decode()
    assert "LV Exec Apr 22" in body
    assert "Hit 90% utilization" in body
    assert "bullet-summary" in body


def test_meeting_detail_404(client):
    assert client.get("/meetings/nope").status_code == 404


def test_meeting_detail_200(client, storage: Storage):
    storage.save_meeting({"id": "m1", "date": "2026-04-22", "title": "x", "summary": "s"})
    resp = client.get("/meetings/m1")
    assert resp.status_code == 200


# --- Goals API ---

def test_api_goals_list(client, storage: Storage):
    storage.add_goal({"title": "g1"})
    assert client.get("/api/goals").get_json()["goals"][0]["title"] == "g1"


def test_api_goal_add(client, storage: Storage):
    r = client.post("/api/goals/add", json={"title": "Ship it", "due": "2026-07-01"})
    assert r.status_code == 200
    assert r.get_json()["title"] == "Ship it"
    assert storage.list_goals()[0]["title"] == "Ship it"


def test_api_goal_add_rejects_empty_title(client):
    assert client.post("/api/goals/add", json={"title": "  "}).status_code == 400


def test_api_goal_toggle(client, storage: Storage):
    g = storage.add_goal({"title": "t"})
    r = client.post(f"/api/goals/{g['id']}/toggle")
    assert r.status_code == 200
    assert r.get_json()["status"] == "complete"


def test_api_goal_toggle_missing(client):
    assert client.post("/api/goals/missing/toggle").status_code == 404


def test_api_goal_move_to_todos(client, storage: Storage):
    g = storage.add_goal({"title": "Migrate ERP"})
    r = client.post(f"/api/goals/{g['id']}/move")
    assert r.status_code == 200
    assert r.get_json()["task"] == "Migrate ERP"


def test_api_goal_update(client, storage: Storage):
    g = storage.add_goal({"title": "old"})
    r = client.patch(f"/api/goals/{g['id']}", json={"title": "new", "due": "2026-09-01"})
    assert r.status_code == 200
    assert r.get_json()["title"] == "new"


def test_api_goal_delete(client, storage: Storage):
    g = storage.add_goal({"title": "t"})
    r = client.delete(f"/api/goals/{g['id']}")
    assert r.status_code == 200
    assert storage.list_goals() == []


def test_api_goals_replace(client, storage: Storage):
    storage.add_goal({"title": "old"})
    r = client.put("/api/goals", json={"goals": [
        {"id": "g1", "title": "fresh", "status": "incomplete"},
    ]})
    assert r.status_code == 200
    assert storage.list_goals()[0]["title"] == "fresh"


# --- Todos API ---

def test_api_todo_add(client, storage: Storage):
    r = client.post("/api/todos", json={"task": "t"})
    assert r.status_code == 200
    assert len(storage.list_todos()) == 1


def test_api_todo_toggle(client, storage: Storage):
    t = storage.add_todo({"task": "t"})
    assert client.post(f"/api/todos/{t['id']}/toggle").get_json()["completed"] is True


def test_api_todo_delete(client, storage: Storage):
    t = storage.add_todo({"task": "t"})
    assert client.delete(f"/api/todos/{t['id']}").status_code == 200


# --- Action items ---

def test_api_action_toggle(client, storage: Storage):
    storage.save_meeting({"id": "m1", "date": "2026-04-22",
                          "action_items": [{"id": "a1", "task": "x"}]})
    r = client.post("/api/action/m1/a1/toggle")
    assert r.status_code == 200


def test_api_action_move(client, storage: Storage):
    storage.save_meeting({"id": "m1", "date": "2026-04-22",
                          "action_items": [{"id": "a1", "owner": "Chris", "task": "move"}]})
    r = client.post("/api/action/m1/a1/move")
    assert r.status_code == 200
    assert r.get_json()["task"] == "move"


# --- Ingest webhook ---

def test_ingest_webhook_requires_api_key(client):
    r = client.post("/api/ingest/readai", json={"meeting": {"id": "x", "date": "2026-04-22"}})
    assert r.status_code == 401


def test_ingest_webhook_filters_non_matching(client, storage: Storage):
    payload = {"meeting": {"id": "off", "title": "Sales call", "date": "2026-04-22"}}
    r = client.post("/api/ingest/readai", json=payload, headers={"X-API-Key": "test-key"})
    assert r.status_code == 200
    assert r.get_json()["status"] == "ignored"
    assert storage.get_meeting("off") is None


def test_ingest_webhook_accepts_lv(client, storage: Storage):
    payload = {"meeting": {
        "id": "lv1", "title": "LV Construction Executive",
        "start_time": "2026-04-22T15:00:00Z",
        "summary": "Notes.", "action_items": [{"owner": "Chris", "task": "x"}],
    }}
    r = client.post("/api/ingest/readai", json=payload, headers={"X-API-Key": "test-key"})
    assert r.status_code == 200
    assert r.get_json()["status"] == "ok"
    m = storage.get_meeting("lv1")
    assert m is not None
    # Action items got IDs assigned at ingest
    assert m["action_items"][0]["id"].startswith("ai_")


def test_ingest_maps_readai_text_to_task(client, storage: Storage):
    """Read.ai sends action items as {id, text, completed}; ingest should populate task."""
    payload = {"meeting": {
        "id": "rai1", "title": "LV Construction Executive",
        "start_time": "2026-04-28T15:00:00Z",
        "summary": "s",
        "action_items": [
            {"id": "ai_1", "text": "Tom will obtain proposals", "completed": False},
        ],
    }}
    r = client.post("/api/ingest/readai", json=payload, headers={"X-API-Key": "test-key"})
    assert r.status_code == 200
    m = storage.get_meeting("rai1")
    assert m["action_items"][0]["task"] == "Tom will obtain proposals"


def test_portal_renders_text_only_action_items(client, storage: Storage):
    storage.save_meeting({
        "id": "legacy", "date": "2026-04-28", "title": "LV Exec",
        "summary": "",
        "action_items": [{"id": "ai_1", "text": "Bob will finalize EOS", "completed": False}],
    })
    body = client.get("/").data.decode()
    assert "Bob will finalize EOS" in body


def test_extract_owner_simple():
    from app.ingest import _extract_owner
    assert _extract_owner("Bob Kennedy will finalize EOS") == "Bob Kennedy"
    assert _extract_owner("Pedro Rosales, Greg Smith, and Grady Lakamp will review") == "Pedro Rosales, Greg Smith, and Grady Lakamp"
    assert _extract_owner("It will be reviewed") == ""


def test_ingest_extracts_owner(client, storage: Storage):
    payload = {"meeting": {
        "id": "owner1", "title": "LV Construction Executive",
        "start_time": "2026-04-28T15:00:00Z",
        "summary": "s",
        "action_items": [
            {"id": "ai_1", "text": "Bob Kennedy will finalize EOS framework", "completed": False},
        ],
    }}
    r = client.post("/api/ingest/readai", json=payload, headers={"X-API-Key": "test-key"})
    assert r.status_code == 200
    assert storage.get_meeting("owner1")["action_items"][0]["owner"] == "Bob Kennedy"


def test_move_text_only_action_to_todos_carries_text(client, storage: Storage):
    storage.save_meeting({
        "id": "m1", "date": "2026-04-28",
        "action_items": [{"id": "ai_1", "text": "Send the report", "completed": False}],
    })
    r = client.post("/api/action/m1/ai_1/move")
    assert r.status_code == 200
    todos = storage.list_todos()
    assert len(todos) == 1 and todos[0]["task"] == "Send the report"


def test_ingest_purges_completed_todos(client, storage: Storage):
    t = storage.add_todo({"task": "old"})
    storage.toggle_todo(t["id"])  # mark complete
    payload = {"meeting": {
        "id": "lv2", "title": "LV Executive", "start_time": "2026-04-22T15:00:00Z",
        "summary": "s", "action_items": [],
    }}
    r = client.post("/api/ingest/readai", json=payload, headers={"X-API-Key": "test-key"})
    assert r.status_code == 200
    assert storage.list_todos() == []  # completed todo purged
