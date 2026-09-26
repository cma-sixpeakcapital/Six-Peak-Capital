"""To-do dates, owners, drop/archive and the Hit Rate numbers (Bob's 9/26 review,
Chris's decisions 1-5)."""
from datetime import date, datetime, timedelta, timezone

import pytest

from app import create_app, todos as T
from app.todo_metrics import build, on_time, seven_day

ROSTER = ["Bob Kennedy", "Chris Aiello", "Chris Andresen", "Derek Sanders",
          "Grady Lakamp", "Robert Carrega", "Schuyler Dietz", "Tom Taggart"]


def ts(d: date, hour: int = 15) -> str:
    return datetime(d.year, d.month, d.day, hour, tzinfo=timezone.utc).isoformat()


def todo(created: date, owners=("Bob Kennedy",), done: date | None = None, due: date | None = None,
         orig: date | None = None, dropped: date | None = None, **kw):
    t = {"id": kw.pop("id", f"td_{created}_{done}_{owners}"), "task": "x", "owners": list(owners),
         "owner": " & ".join(owners), "created_at": ts(created),
         "due": (due or created + timedelta(days=7)).isoformat(),
         "original_due": (orig or due or created + timedelta(days=7)).isoformat(),
         "completed": done is not None, "completed_at": ts(done) if done else None, "schema": 2}
    if dropped:
        t["dropped_at"] = ts(dropped)
    t.update(kw)
    return t


# ---- lifecycle -----------------------------------------------------------

def test_resolve_owners_maps_short_and_joint_names():
    assert T.resolve_owners("Bob", ROSTER) == ["Bob Kennedy"]
    assert T.resolve_owners("Derek", ROSTER) == ["Derek Sanders"]
    assert T.resolve_owners("Chris Aiello and Grady Lakamp", ROSTER) == ["Chris Aiello", "Grady Lakamp"]
    assert T.resolve_owners("Chris", ROSTER) == ["Chris"]  # ambiguous: kept as typed
    assert T.resolve_owners("MRK", ROSTER) == ["MRK"]
    assert T.resolve_owners(["Tom Taggart", "Andresen"], ROSTER) == ["Tom Taggart", "Chris Andresen"]


def test_parse_due_formats():
    ref = date(2026, 9, 26)
    assert T.parse_due("2026-10-06") == date(2026, 10, 6)
    assert T.parse_due("11/30", ref) == date(2026, 11, 30)
    assert T.parse_due("1/15", ref) == date(2027, 1, 15)
    assert T.parse_due("5/10/26") == date(2026, 5, 10)
    assert T.parse_due("TBD") is None and T.parse_due("") is None and T.parse_due("End of Jan") is None


def test_new_todo_defaults_due_to_seven_days(storage):
    t = storage.add_todo({"owner": "Bob", "task": "Call Pat"})
    created = T.et_date(t["created_at"])
    assert t["due"] == t["original_due"] == (created + timedelta(days=7)).isoformat()
    assert t["due_defaulted"] is True and t["owners"] == ["Bob Kennedy"] and t["owner"] == "Bob Kennedy"


def test_due_changes_are_logged_and_original_stays(storage):
    t = storage.add_todo({"owners": ["Tom Taggart"], "task": "Bid", "due": "2026-10-06"})
    storage.update_todo(t["id"], {"due": "2026-10-13"}, actor="Tom Taggart")
    out = storage.update_todo(t["id"], {"due": "2026-10-20"}, actor="Bob Kennedy")
    assert out["original_due"] == "2026-10-06" and out["due"] == "2026-10-20"
    assert [(c["from"], c["to"], c["by"]) for c in out["due_changes"]] == [
        ("2026-10-06", "2026-10-13", "Tom Taggart"), ("2026-10-13", "2026-10-20", "Bob Kennedy")]
    same = storage.update_todo(t["id"], {"due": "2026-10-20", "task": "Bid v2"})
    assert len(same["due_changes"]) == 2  # no-op date change is not logged


def test_toggle_stamps_and_clears_completion(storage):
    t = storage.add_todo({"task": "x"})
    on = storage.toggle_todo(t["id"])
    assert on["completed"] and on["completed_at"]
    off = storage.toggle_todo(t["id"])
    assert not off["completed"] and off["completed_at"] is None


def test_drop_hides_restore_returns(storage):
    t = storage.add_todo({"task": "maybe"})
    storage.drop_todo(t["id"], "Deal died", actor="Bob Kennedy")
    assert storage.list_todos() == []
    kept = storage.list_all_todos()[0]
    assert kept["drop_reason"] == "Deal died" and kept["dropped_by"] == "Bob Kennedy"
    storage.restore_todo(t["id"])
    assert [x["id"] for x in storage.list_todos()] == [t["id"]]


def test_completed_todos_are_archived_not_deleted(storage):
    a = storage.add_todo({"task": "done one"})
    storage.add_todo({"task": "open one"})
    storage.toggle_todo(a["id"])
    assert storage.purge_completed_todos() == 1
    assert [x["task"] for x in storage.list_todos()] == ["open one"]
    everything = storage.list_all_todos()
    assert len(everything) == 2 and next(x for x in everything if x["id"] == a["id"])["archived_at"]


def test_migration_backfills_old_todos(storage):
    data = storage.load_rocks()
    data["todos"] = [
        {"id": "td_a", "owner": "Bob", "task": "a", "due": "", "completed": False, "created_at": ts(date(2026, 8, 9))},
        {"id": "td_b", "owner": "Chris Aiello and Grady Lakamp", "task": "b", "due": "", "completed": True,
         "created_at": ts(date(2026, 9, 16))},
        {"id": "td_c", "owner": "Bob Kennedy", "task": "c", "due": "2026-10-31", "completed": False,
         "created_at": ts(date(2026, 9, 14))},
        {"id": "td_d", "owner": "MRK", "task": "d", "due": "soon", "completed": False,
         "created_at": ts(date(2026, 9, 16))},
    ]
    storage.save_rocks(data)
    storage.record_audit({"action": "Toggle to-do done", "at": "2026-09-25T18:00:00+00:00",
                          "changes": [{"item": "todo:td_b", "after": {"completed": True}}]})
    assert storage.migrate_todos() == 4
    by = {t["id"]: t for t in storage.list_all_todos()}
    assert by["td_a"]["due"] == by["td_a"]["original_due"] == "2026-10-06" and by["td_a"]["due_set_at_rollout"]
    assert by["td_a"]["owners"] == ["Bob Kennedy"]
    assert by["td_b"]["owners"] == ["Chris Aiello", "Grady Lakamp"]
    assert by["td_b"]["completed_at"] == "2026-09-25T18:00:00+00:00"
    assert by["td_c"]["due"] == "2026-10-31" and "due_set_at_rollout" not in by["td_c"]
    assert by["td_d"]["owners"] == ["MRK"] and by["td_d"]["due_note"] == "soon"
    assert storage.migrate_todos() == 0  # idempotent


def test_app_startup_runs_migration(tmp_config):
    app = create_app(tmp_config)
    st = app.config["STORAGE"]
    data = st.load_rocks()
    data["todos"] = [{"id": "td_x", "owner": "Derek", "task": "x", "due": "", "completed": False,
                      "created_at": ts(date(2026, 9, 16))}]
    st.save_rocks(data)
    create_app(tmp_config)
    t = create_app(tmp_config).config["STORAGE"].list_all_todos()[0]
    assert t["schema"] == 2 and t["owners"] == ["Derek Sanders"]


# ---- metrics -------------------------------------------------------------

TODAY = date(2026, 11, 10)  # a Tuesday


def test_seven_day_rate_excludes_dropped_and_counts_late_as_miss():
    c = date(2026, 11, 1)  # mark 11/8, inside the last 7 days
    items = [todo(c, done=date(2026, 11, 5), id="1"), todo(c, done=date(2026, 11, 8), id="2"),
             todo(c, done=date(2026, 11, 9), id="3"),  # late
             todo(c, id="4"),  # open past its mark
             todo(c, dropped=date(2026, 11, 7), id="5")]  # dropped: out of the rate
    f = seven_day(items, TODAY - timedelta(days=7), TODAY)
    assert (f["n"], f["d"], f["pct"]) == (2, 4, 50)


def test_nothing_scored_before_tracking_began():
    old = todo(date(2026, 9, 10), done=date(2026, 9, 12))  # mark 9/17 < 9/26
    assert seven_day([old], date(2026, 9, 1), date(2026, 9, 30))["d"] == 0


def test_on_time_uses_original_due_so_pushing_does_not_help():
    items = [
        todo(date(2026, 10, 1), orig=date(2026, 10, 8), due=date(2026, 10, 20), done=date(2026, 10, 19), id="pushed"),
        todo(date(2026, 10, 1), orig=date(2026, 10, 8), done=date(2026, 10, 7), id="ontime"),
        todo(date(2026, 10, 1), orig=date(2026, 10, 9), id="open-late"),
        todo(date(2026, 11, 5), orig=date(2026, 11, 20), id="not-due-yet"),
        todo(date(2026, 11, 5), orig=date(2026, 11, 20), done=date(2026, 11, 6), id="done-early"),
    ]
    f = on_time(items, date(2026, 9, 1), TODAY)
    assert (f["n"], f["d"]) == (2, 4)


def test_open_overdue_age_and_buckets():
    items = [todo(date(2026, 11, 8), id="a"),                               # 2 days
             todo(date(2026, 10, 30), due=date(2026, 11, 20), id="b"),      # 11 days
             todo(date(2026, 10, 20), id="c"),                              # 21 days, overdue
             todo(date(2026, 9, 1), due=date(2026, 10, 6), id="d"),         # 70 days, overdue
             todo(date(2026, 9, 1), done=date(2026, 9, 5), id="e"),         # done: not open
             todo(date(2026, 9, 1), dropped=date(2026, 10, 2), id="f")]     # dropped: not open
    s = build(items, TODAY, {"start": "2026-09-01"}, ROSTER)
    assert (s["open"], s["overdue"], s["oldest_age"]) == (4, 2, 70)
    assert s["avg_age"] == round((2 + 11 + 21 + 70) / 4, 1)
    assert [b["count"] for b in s["buckets"]] == [1, 1, 1, 1]
    assert s["dropped"] == 1


def test_owner_table_credits_shared_ranks_with_floor():
    c = date(2026, 10, 20)
    items = []
    # Tom: 17 of 20 done within 7 days (85%)
    for i in range(20):
        items.append(todo(c, owners=["Tom Taggart"], done=c + timedelta(days=3 if i < 17 else 9), id=f"t{i}"))
    # Grady: 2 of 2 (100%) - too few to rank
    for i in range(2):
        items.append(todo(c, owners=["Grady Lakamp"], done=c + timedelta(days=1), id=f"g{i}"))
    # Shared Bob & Chris: credited to both
    for i in range(5):
        items.append(todo(c, owners=["Bob Kennedy", "Chris Aiello"], done=c + timedelta(days=2), id=f"bc{i}"))
    items.append(todo(c, owners=["MRK"], id="ext"))
    s = build(items, TODAY, {"start": "2026-09-01"}, ROSTER)
    rows = {r["owner"]: r for r in s["owners"]}
    assert rows["Tom Taggart"]["rate"] == {"n": 17, "d": 20, "pct": 85} and rows["Tom Taggart"]["ranked"]
    assert rows["Grady Lakamp"]["rate"]["d"] == 2 and not rows["Grady Lakamp"]["ranked"]
    assert rows["Bob Kennedy"]["rate"]["d"] == rows["Chris Aiello"]["rate"]["d"] == 5
    assert "MRK" not in rows and rows["Unassigned"]["open"] == 1 and not rows["Unassigned"]["ranked"]
    ranked = [r["owner"] for r in s["owners"] if r["ranked"]]
    assert ranked[-1] == "Tom Taggart" and "Grady Lakamp" not in ranked
    order = [r["owner"] for r in s["owners"]]
    assert order.index("Grady Lakamp") > order.index("Tom Taggart")
    assert order[-1] == "Unassigned"


def test_trend_is_13_tuesday_weeks():
    t = build([todo(date(2026, 10, 27), done=date(2026, 10, 28))], TODAY, None, ROSTER)["trend"]
    assert len(t) == 13 and t[-1]["week_ending"] == "2026-11-10"
    assert all(date.fromisoformat(p["week_ending"]).weekday() == 1 for p in t)
    assert [p for p in t if p["d"]] == [{"week_ending": "2026-11-03", "n": 1, "d": 1, "pct": 100}]


# ---- pages and API -------------------------------------------------------

@pytest.fixture
def app_client(tmp_config):
    app = create_app(tmp_config)
    st = app.config["STORAGE"]
    data = st.load_rocks()
    data["quarters"] = [{"id": "Q4 2026", "label": "Q4 2026", "start": "2026-09-01", "end": "2026-11-30"}]
    data.setdefault("company_rocks", []).append({"id": "cr_q4", "title": "Bonding", "owner": "Bob Kennedy",
                                                 "quarter": "Q4 2026", "status": "incomplete"})
    st.save_rocks(data)
    return app.test_client(), st


def test_page_has_dividers_owner_picker_and_todo_hit_rate(app_client):
    c, st = app_client
    st.add_todo({"owners": ["Tom Taggart"], "task": "Visible task", "due": "2026-10-06"})
    html = c.get("/").get_data(as_text=True)
    assert 'id="rocks-divider"' in html and "<span>Q4 Rocks</span>" in html
    assert 'id="todos-divider"' in html
    assert 'name="owners" value="Bob Kennedy"' in html and 'type="date"' in html
    assert "7-day completion" in html and "standard 90%" in html and "Open to-dos by age" in html
    assert "drop-todo-btn" in html


def test_drop_and_restore_endpoints_are_audited(app_client):
    c, st = app_client
    t = st.add_todo({"task": "Drop me"})
    r = c.post(f"/api/todos/{t['id']}/drop", json={"reason": "No longer needed"},
               headers={"X-Actor": "Bob Kennedy"})
    assert r.status_code == 200 and r.get_json()["drop_reason"] == "No longer needed"
    html = c.get("/").get_data(as_text=True)
    assert "Dropped this quarter (1)" in html
    assert c.post(f"/api/todos/{t['id']}/restore").status_code == 200
    assert c.post("/api/todos/nope/drop").status_code == 404
    actions = [e["action"] for e in st.list_audit()]
    assert "Drop to-do" in actions and "Restore dropped to-do" in actions


def test_add_and_edit_with_owner_pick_list(app_client):
    c, st = app_client
    r = c.post("/api/todos", json={"task": "Joint", "owners": ["Chris Aiello", "Grady Lakamp"],
                                   "owner_other": "MRK", "due": ""})
    t = r.get_json()
    assert t["owners"] == ["Chris Aiello", "Grady Lakamp", "MRK"] and t["due_defaulted"]
    r = c.patch(f"/api/todos/{t['id']}", json={"owners": ["Tom Taggart"], "owner_other": "", "due": "2026-12-01"},
                headers={"X-Actor": "Tom Taggart"})
    out = r.get_json()
    assert out["owner"] == "Tom Taggart" and out["due_changes"][-1]["by"] == "Tom Taggart"


def test_scoreboard_api_includes_todo_numbers(app_client):
    c, st = app_client
    st.add_todo({"task": "x"})
    body = c.get("/api/scoreboard").get_json()
    assert body["todos"]["standard_pct"] == 90 and body["todos"]["open"] == 1
    assert len(body["todos"]["trend"]) == 13
