"""Portal + API render the scoreboard, quarter banner and parked issues."""
import copy

from app.quarter_rollover import apply_rollover, load_json
from tests.test_quarter_rollover import DATA, FIXTURE, MIG


def _rolled_doc():
    after, _ = apply_rollover(copy.deepcopy(load_json(FIXTURE)), load_json(MIG), load_json(DATA))
    return after


def test_portal_renders_scoreboard_sections(client, storage):
    storage.save_rocks(_rolled_doc())
    body = client.get("/").data.decode()
    for needle in ("Scoreboard", "Leaderboard", "Q3 2026 post-mortem", "Issues List",
                   "Rule this quarter", "#1", "Controllable action", "official 18/32",
                   "Q4 2026", "77 days left" if False else "days left"):
        assert needle in body, needle
    # Leaderboard: Chris row first, Grady last.
    assert body.index("Chris Aiello") < body.index("Grady Lakamp")
    # Legacy Q2 rocks in the "Earlier" list, not a scored block.
    assert "pre-EOS format" in body


def test_portal_before_rollover_still_renders(client, storage):
    # The deploy lands before the migration runs: Q3 live, no registry, no results.
    storage.save_rocks(load_json(FIXTURE))
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "Company Rocks" in body
    assert "Leaderboard" in body  # Q3 shows as the in-flight quarter
    assert "post-mortem" not in body


def test_api_scoreboard_and_quarters(client, storage):
    storage.save_rocks(_rolled_doc())
    sb = client.get("/api/scoreboard").get_json()
    assert sb["last_closed"]["official"]["complete"] == 18
    assert sb["leaderboard"][0]["owner"] == "Chris Aiello"
    q = client.get("/api/quarters").get_json()
    assert q["current"]["id"] == "Q4 2026"
    assert len(q["parked_issues"]) == 7


def test_patch_result_validated(client, storage):
    storage.save_rocks(_rolled_doc())
    rid = "r_q42026_01"
    ok = client.patch(f"/api/rocks/{rid}", json={"result": "carry_forward", "result_note": "x"})
    assert ok.status_code == 200 and ok.get_json()["result"] == "carry_forward"
    bad = client.patch(f"/api/rocks/{rid}", json={"result": "meh"})
    assert bad.status_code == 400


def test_kpis_server_side(client, storage):
    storage.save_rocks(_rolled_doc())
    body = client.get("/").data.decode()
    assert '<b id="chip-rocks">24</b>' in body
    assert 'id="kpi-rocks-v">0<small>/24</small>' in body
