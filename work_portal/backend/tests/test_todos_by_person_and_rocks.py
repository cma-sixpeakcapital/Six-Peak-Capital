"""To-dos grouped by person; rock restatements kept off the list (Chris, 10/13/2026)."""
from app import todos as T
from app.ingest import IngestService
from app.scoring import ROSTER

from .conftest import FakeSummarizer

ROCKS = {
    "company_rocks": [
        {"id": "cr1", "owner": "Chris Aiello", "title": "Bonding independence from Krueger — memo + dated path"},
        {"id": "cr_old", "owner": "Chris Aiello", "title": "Bonding capacity study", "archived": True},
    ],
    "rocks": {
        "Derek Sanders": [{"id": "r1", "title": "GrindAI implementation roadmap (discovery memo)"}],
        "Tom Taggart": [{"id": "r2", "title": "LV capacity — defined scaling process + memo"}],
        "Chris Andresen": [{"id": "r3", "title": "Francis Citi draw + R4 reporting SOP"}],
        "Schuyler Dietz": [{"id": "r4", "title": "Assist the Foundation in Stifel-driven due diligence"}],
    },
    "todos": [],
}

# Live action items from the 10/6 L10 (Read.ai wording, typos included).
ROCK_LIKE = [
    ("Derek Sanders will prepare the Grind AI implementation roadmap memo for review at the off-site with Jonah.", "r1"),
    ("Tom Taggart will coordinate with Grady and the team to refine the capacity-scaling process and memo", "r2"),
    ("Chris Andresen will finalize the Frankfurt City Draw and R4 reporting.", "r3"),
]
REAL_TODOS = [
    "Schuyler Dietz will continue due diligence on the Victoria Park site during the 60-day contingency period",
    "Chris Aiello will get answers from HVN about what bonding capacity may be available next year.",
    "Chris Aiello will send the memo to Stain to explore potential equity or dilution options related to bonding capacity.",
    "Bob Kennedy will forward the funding-bridge package to the Sting Group after the scheduled confirmation call.",
    "Chris Andresen will identify a third potential lender to request financing information from.",
    "Schuyler Dietz will rewrite the sub-debt rock.",
]


def _owners(text):
    from app.ingest import _extract_owner
    return T.resolve_owners(_extract_owner(text), ROSTER)


def test_rock_restatements_match_their_rock():
    for text, rock_id in ROCK_LIKE:
        rock = T.match_rock(text, _owners(text), ROCKS, ROSTER)
        assert rock is not None and rock["id"] == rock_id, text


def test_real_todos_do_not_match():
    for text in REAL_TODOS:
        assert T.match_rock(text, _owners(text), ROCKS, ROSTER) is None, text


def test_only_the_owners_rocks_count():
    text = "Bob Kennedy will refine the LV capacity scaling process memo"
    assert T.match_rock(text, ["Bob Kennedy"], ROCKS, ROSTER) is None
    assert T.match_rock(text, ["Tom Taggart"], ROCKS, ROSTER)["id"] == "r2"


def test_archived_rocks_ignored():
    assert T.match_rock("Chris Aiello will finish the bonding capacity study", ["Chris Aiello"],
                        ROCKS, ROSTER) is None


def test_action_items_matching_rocks_are_not_converted():
    import copy
    data = copy.deepcopy(ROCKS)
    meeting = {"id": "m1", "title": "Six Peak L10", "date": "2026-10-13",
               "action_items": [{"id": "a1", "task": ROCK_LIKE[0][0]},
                                {"id": "a2", "task": REAL_TODOS[1]}]}
    created = T.todos_from_action_items(meeting, data, ROSTER)
    assert [t["task"] for t in created] == [REAL_TODOS[1]]
    a1, a2 = meeting["action_items"]
    assert a1["rock_id"] == "r1" and "GrindAI" in a1["rock_title"] and not a1.get("todo_id")
    assert a2["todo_id"]
    # re-run (webhook re-send) stays put
    assert T.todos_from_action_items(meeting, data, ROSTER) == []
    # "Make it a to-do" override
    a1["keep_as_todo"] = True
    a1.pop("rock_id")
    created = T.todos_from_action_items(meeting, data, ROSTER)
    assert len(created) == 1 and a1["todo_id"] == created[0]["id"]


def test_keep_todo_route(client):
    import copy
    with client.application.app_context():
        from app import routes
        storage = routes._get_storage()
        data = storage.load_rocks()
        data.update(copy.deepcopy({k: ROCKS[k] for k in ("company_rocks", "rocks")}))
        storage.save_rocks(data)
        IngestService(storage=storage, summarizer=FakeSummarizer()).ingest_webhook({"meeting": {
            "id": "m9", "title": "Six Peak L10", "start_time": "2026-10-13T15:00:00Z", "summary": "s",
            "action_items": [{"text": ROCK_LIKE[1][0]}]}})
        assert storage.list_todos() == []
        item = storage.get_meeting("m9")["action_items"][0]
        assert item["rock_id"] == "r2"
    page = client.get("/meetings/m9")
    assert page.status_code == 200 and b"Make it a to-do" in page.data
    res = client.post(f"/api/action/m9/{item['id']}/keep-todo")
    assert res.status_code == 200
    with client.application.app_context():
        todos = storage.list_todos()
        assert len(todos) == 1 and todos[0]["owners"] == ["Tom Taggart"]
        assert storage.get_meeting("m9")["action_items"][0]["todo_id"] == todos[0]["id"]


def test_owner_parsing_oxford_and_placeholder():
    assert T.resolve_owners("Bob Kennedy, Chris Aiello, and Derek Sanders", ROSTER) == \
        ["Bob Kennedy", "Chris Aiello", "Derek Sanders"]
    assert T.resolve_owners("Meeting participant", ROSTER) == []


def test_group_by_owner():
    todos = [
        {"id": "1", "owners": ["Tom Taggart"], "task": "a", "due": "2026-10-20"},
        {"id": "2", "owners": ["Bob Kennedy", "Chris Aiello"], "task": "shared", "due": "2026-10-10"},
        {"id": "3", "owner": "Bob Kennedy & Chris Aiello & and Derek Sanders", "task": "old row", "due": "2026-10-30"},
        {"id": "4", "owner": "Meeting participant", "task": "nobody", "due": "2026-10-30"},
        {"id": "5", "owners": ["MRK"], "task": "outside", "due": "2026-10-30"},
        {"id": "6", "owners": ["Bob Kennedy"], "task": "done", "due": "2026-10-01", "completed": True},
    ]
    groups = T.group_by_owner(todos, ROSTER)
    names = [g["name"] for g in groups]
    assert names == ["Bob Kennedy", "Chris Aiello", "Derek Sanders", "Tom Taggart", "MRK", "Unassigned"]
    bob = groups[0]
    assert [t["id"] for t in bob["todos"]] == ["2", "3", "6"]  # open by due, done last
    assert bob["open"] == 2 and bob["done"] == 1
    assert bob["shared"]["2"] == ["Chris Aiello"]
    assert groups[2]["shared"]["3"] == ["Bob Kennedy", "Chris Aiello"]


def test_portal_renders_groups(client):
    client.post("/api/todos", json={"task": "Call Chase", "owners": ["Bob Kennedy", "Tom Taggart"]})
    page = client.get("/")
    assert page.status_code == 200
    html = page.data.decode()
    assert html.count('class="todo-person"') == 2
    assert "Shared with Tom Taggart" in html and "Shared with Bob Kennedy" in html
