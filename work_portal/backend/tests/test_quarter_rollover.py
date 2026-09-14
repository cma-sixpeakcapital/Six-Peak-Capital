"""Q3 2026 -> Q4 2026 rollover on a fixture mirroring the live rocks_doc (9/14)."""
import copy
import json
from pathlib import Path

import pytest

from app.quarter_rollover import apply_rollover, format_plan, load_json
from app.scoring import leaderboard, score_quarter, scoreboard

BACKEND = Path(__file__).resolve().parent.parent
FIXTURE = BACKEND / "tests" / "fixtures" / "live_rocks_2026-09-14.json"
DATA = BACKEND / "data" / "q4_2026" / "Q4_rocks_data.json"
MIG = BACKEND / "data" / "q4_2026" / "Q4_rocks_migration.json"


@pytest.fixture
def live():
    return load_json(FIXTURE)


@pytest.fixture
def rolled(live):
    after, plan = apply_rollover(copy.deepcopy(live), load_json(MIG), load_json(DATA))
    return after, plan


def _all(data):
    out = list(data["company_rocks"])
    for rs in data["rocks"].values():
        out.extend(rs)
    return out


def test_fixture_mirrors_live_counts(live):
    q3 = [r for r in _all(live) if r.get("quarter") == "Q3 2026" and not r.get("deferred")]
    assert len(q3) == 31  # + the untagged Ramsgate rock = 32
    assert sum(1 for r in q3 if r["status"] == "complete") == 17


def test_plan_is_clean(rolled):
    after, plan = rolled
    assert plan["closeout_missing"] == []
    assert plan["closeout_invalid"] == []
    assert plan["successor_missing"] == []
    assert plan["fixup_missing"] == []
    assert "MISSING" not in format_plan(plan)


def test_every_q3_rock_gets_a_result_and_is_archived(rolled):
    after, _ = rolled
    q3 = [r for r in _all(after) if r.get("quarter") == "Q3 2026"]
    assert len(q3) == 33  # 32 scored + 1 deferred
    assert all(r.get("archived") for r in q3)
    assert all(r.get("result") in {"complete", "carry_forward", "task", "killed", "deferred"} for r in q3)
    results = {}
    for r in q3:
        results[r["result"]] = results.get(r["result"], 0) + 1
    assert results == {"complete": 19, "carry_forward": 7, "task": 3, "killed": 3, "deferred": 1}


def test_ramsgate_fixup_makes_chris_seven_for_seven(rolled):
    after, plan = rolled
    assert any(f["title"] == "9033 Ramsgate PM Proposals" for f in plan["fixups_applied"])
    s = score_quarter(after, "Q3 2026")
    chris = next(o for o in s["owners"] if o["owner"] == "Chris Aiello")
    assert (chris["complete"], chris["owned"]) == (7, 7)


def test_q3_team_score_and_official_record(rolled):
    after, _ = rolled
    s = score_quarter(after, "Q3 2026")
    assert (s["complete"], s["total"]) == (19, 32)      # per-rock tally
    assert s["closed"] is True
    assert s["official"] == {"complete": 17, "total": 32, "source": "Chris Aiello 9/14"}
    assert s["company_total"] == 7  # deferred excluded


def test_task_dispositions_become_todos_or_link_existing(rolled):
    after, plan = rolled
    created = {t["task"] for t in plan["todos_created"]}
    assert created == {"401(k) attorney memo — close out or kill",
                       "Finalize restructure of equity positions under SPC & CLH2"}
    # Bob's BD-agreement to-do already existed (from an action item) — linked, not duplicated.
    assert len(plan["todos_linked"]) == 1
    linked = next(t for t in after["todos"] if t["id"] == "td_a2")
    assert linked["source"]["rock_id"] == "cr_q3_03"
    assert sum(1 for t in after["todos"] if "consulting agreement" in t["task"]) == 1
    for t in after["todos"]:
        if t["id"].startswith("td_q32026conv"):
            assert t["source"]["label"] == "from rock (Q3 2026)"
            assert t["completed"] is False


def test_q4_loaded_by_owner_with_rank_and_milestones(rolled):
    after, plan = rolled
    assert len(plan["loaded_company"]) == 5
    assert len(plan["loaded_individual"]) == 19
    active_company = [r for r in after["company_rocks"] if not r.get("archived")]
    assert [r["rank"] for r in active_company] == [1, 2, 3, 4, 5]
    assert all(r["quarter"] == "Q4 2026" and r["status"] == "incomplete" for r in active_company)
    assert active_company[0]["milestones"]["30"].startswith("9/30")
    assert active_company[0]["controllable_action"]
    counts = {o: len([r for r in rs if r.get("quarter") == "Q4 2026"]) for o, rs in after["rocks"].items()}
    assert {k: v for k, v in counts.items() if v} == {
        "Chris Aiello": 2, "Bob Kennedy": 1, "Chris Andresen": 3, "Derek Sanders": 4,
        "Robert Carrega": 2, "Schuyler Dietz": 4, "Tom Taggart": 3,
    }


def test_carry_forwards_link_to_successors(rolled):
    after, plan = rolled
    assert len(plan["successors_linked"]) == 8  # 7 carry-forwards + the deferred bonding rock
    by_id = {r["id"]: r for r in _all(after)}
    loc = next(r for r in _all(after) if r["title"] == "Put in place a non-recourse revolving LOC")
    assert by_id[loc["successor_id"]]["title"] == "Working-capital facility — signed term sheet"
    assert loc["id"] in by_id[loc["successor_id"]]["predecessor_ids"]


def test_quarter_registry(rolled):
    after, _ = rolled
    ids = [q["id"] for q in after["quarters"]]
    assert "Q3 2026" in ids and "Q4 2026" in ids
    q3 = next(q for q in after["quarters"] if q["id"] == "Q3 2026")
    q4 = next(q for q in after["quarters"] if q["id"] == "Q4 2026")
    assert q3["closed"] is True and q4["closed"] is False
    assert q4["end"] == "2026-11-30" and q4["offsite"].startswith("2026-10-19")
    assert len(after["parked_issues"]) == 7


def test_rollover_is_idempotent(rolled):
    after, _ = rolled
    again, plan2 = apply_rollover(copy.deepcopy(after), load_json(MIG), load_json(DATA))
    assert again == after
    assert plan2["closeout_stamped"] == [] and plan2["todos_created"] == []
    assert plan2["loaded_company"] == [] and plan2["loaded_individual"] == []
    assert plan2["archived"] == [] and plan2["successors_linked"] == []


def test_q2_rocks_untouched_and_unscored(rolled):
    after, _ = rolled
    q2 = [r for r in _all(after) if r.get("quarter") == "Q2 2026"]
    assert q2 and all(r.get("archived") and not r.get("result") for r in q2)
    assert all(s["quarter"] != "Q2 2026" for s in scoreboard(after)["quarters"])


def test_leaderboard_order_and_streaks(rolled):
    after, _ = rolled
    lb = leaderboard(after)
    assert [r["owner"] for r in lb[:2]] == ["Chris Aiello", "Tom Taggart"]  # both 100%, Chris owned more
    assert lb[0]["streak"] == 1 and lb[0]["cum_pct"] == 100
    assert lb[-1]["owner"] == "Grady Lakamp" and lb[-1]["cum_pct"] == 0
    assert all(r["live"]["quarter"] == "Q4 2026" for r in lb if r["live"])
    grady = next(r for r in lb if r["owner"] == "Grady Lakamp")
    assert grady["live"]["owned"] == 0  # no Q4 rocks
    assert len(lb) == 8  # roster only — joint-owner Q2 keys never appear


def test_scoreboard_shape(rolled):
    after, _ = rolled
    sb = scoreboard(after)
    assert [q["quarter"] for q in sb["quarters"]] == ["Q3 2026", "Q4 2026"]
    assert sb["live"]["total"] == 24 and sb["live"]["complete"] == 0
    assert sb["last_closed"]["quarter"] == "Q3 2026"
    assert sb["milestones"]["end"] == "2026-11-30"
    assert len(sb["postmortem"]) == 13
    assert sb["postmortem"][0]["result"] == "carry_forward"


def test_live_status_toggle_drives_open_quarter_score(rolled):
    after, _ = rolled
    rock = next(r for r in after["company_rocks"] if r.get("rank") == 1)
    rock["status"] = "complete"
    s = score_quarter(after, "Q4 2026")
    assert s["complete"] == 1
    chris = next(o for o in s["owners"] if o["owner"] == "Chris Aiello")
    assert chris["complete"] == 1 and chris["owned"] == 4
