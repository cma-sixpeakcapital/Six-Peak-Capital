"""IDS issues list (Chris, 10/7/2026)."""


def _meeting(storage, mid="2026-10-06"):
    storage.save_meeting({"id": mid, "date": mid, "title": "Six Peak Capital - Weekly L10",
                          "summary": "s", "action_items": []})


def test_add_solve_with_todo_and_reopen(client, storage):
    r = client.post("/api/issues", json={"title": "Crenshaw crew idle until utilities",
                                         "owners": ["Grady Lakamp"], "detail": "Water/power dates unknown"})
    assert r.status_code == 200
    iid = r.get_json()["id"]
    assert r.get_json()["owners"] == ["Grady Lakamp"]
    r = client.post(f"/api/issues/{iid}/solve",
                    json={"resolution": "Get a water date from Charles by 10/13", "make_todo": True})
    body = r.get_json()
    assert body["issue"]["status"] == "solved"
    todo = body["todo"]
    assert todo["task"] == "Get a water date from Charles by 10/13"
    assert todo["owners"] == ["Grady Lakamp"]
    assert todo["source"]["type"] == "ids_issue"
    assert any(t["id"] == todo["id"] for t in storage.list_todos())
    r = client.post(f"/api/issues/{iid}/reopen")
    assert r.get_json()["status"] == "open"


def test_solve_without_todo_and_drop(client, storage):
    a = client.post("/api/issues", json={"title": "A"}).get_json()["id"]
    b = client.post("/api/issues", json={"title": "B"}).get_json()["id"]
    r = client.post(f"/api/issues/{a}/solve", json={"resolution": "done", "make_todo": False})
    assert r.get_json()["todo"] is None
    assert storage.list_todos() == []
    r = client.post(f"/api/issues/{b}/drop", json={"reason": "not ours"})
    assert r.get_json()["status"] == "dropped"
    v = client.get("/api/issues").get_json()
    assert v["open"] == [] and len(v["closed"]) == 2


def test_validation_and_404(client):
    assert client.post("/api/issues", json={"title": "  "}).status_code == 400
    assert client.post("/api/issues/nope/solve", json={}).status_code == 404
    assert client.put("/api/meetings/nope/issues", json={"issues": []}).status_code == 404


def test_meeting_upsert_idempotent_and_respects_portal_status(client, storage):
    _meeting(storage)
    payload = {"issues": [
        {"title": "Bonding capacity and working capital", "owner": "Chris Aiello",
         "detail": "Krueger 3.25%; no cheaper alternative", "status": "solved",
         "resolution": "Memo to Steyn on equity/dilution; HVN 2027 outlook"},
        {"title": "Crenshaw crew idle waiting on utilities", "owner": "Grady"},
    ]}
    r = client.put("/api/meetings/2026-10-06/issues", json=payload)
    assert r.status_code == 200 and r.get_json()["added"] == 2
    v = client.get("/api/issues").get_json()
    assert [i["title"] for i in v["open"]] == ["Crenshaw crew idle waiting on utilities"]
    crenshaw = v["open"][0]
    assert crenshaw["owners"] == ["Grady Lakamp"]
    assert crenshaw["source"]["label"] == "from L10 10/6"
    # Drop it in the portal, then the scheduled task re-sends the same list.
    client.post(f"/api/issues/{crenshaw['id']}/drop", json={})
    r = client.put("/api/meetings/2026-10-06/issues", json=payload)
    assert r.get_json()["added"] == 0
    v = client.get("/api/issues").get_json()
    assert v["open"] == [] and len(v["closed"]) == 2


def test_bad_meeting_payload(client, storage):
    _meeting(storage)
    assert client.put("/api/meetings/2026-10-06/issues", json={"issues": "x"}).status_code == 400
    assert client.put("/api/meetings/2026-10-06/issues",
                      json={"issues": [{"title": "t", "status": "weird"}]}).status_code == 400


def test_dashboard_ids_section_between_todos_and_rock_results(client, storage):
    client.post("/api/issues", json={"title": "Troost start before contract"})
    html = client.get("/").get_data(as_text=True)
    assert "Troost start before contract" in html
    assert html.index('id="todos"') < html.index('id="ids"') < html.index('id="hitrate-divider"')


def test_issue_edits_are_in_change_log(client, storage):
    client.post("/api/issues", json={"title": "Logged issue"}, headers={"X-Actor": "Bob Kennedy"})
    rows = storage.list_audit(limit=5)
    assert any(r.get("action") == "Add IDS issue" for r in rows)
