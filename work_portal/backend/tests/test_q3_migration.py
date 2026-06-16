"""Tests for the Q3 2026 rock rollover (app/q3_migration.py).

Pure-function tests: they build a doc shaped like the live rocks_doc and run
the transform — no DB required. Also covers the new in_progress status and the
group-by-owner / archive helpers in routes.
"""
import copy
import json
from pathlib import Path

import pytest

from app.q3_migration import (
    Q3_DATA_PATH, Q3_MIGRATION_PATH, apply_migration, load_json,
)
from app.routes import _collect_archive, _group_active_by_owner, _split_company_rocks
from app.storage import STATUSES, Storage


# A doc shaped like the live rocks_doc on 2026-06-16: 1 company rock
# (AI Workflow) + the 21 individual old rocks across combined-owner keys,
# plus the 10 existing to-dos (only the rock-sourced one matters here).
def _live_like_doc() -> dict:
    return {
        "company_rocks": [
            {"id": "cr_ai", "title": "AI Workflow", "status": "incomplete", "notes": "x"},
        ],
        "rocks": {
            "Bob Kennedy": [
                {"id": "r21", "title": "MRK Negotiations and finalize MOU", "status": "incomplete"},
                {"id": "r25", "title": "LIHTC Parking Study Oversight", "status": "complete"},
            ],
            "Bob Kennedy & Chris Aiello": [
                {"id": "r22", "title": "2859 Francis Debt & Equity Execution", "status": "incomplete"},
            ],
            "Chris Aiello": [
                {"id": "r10", "title": "Update BBC memo for 4/13 IC meeing", "status": "complete"},
                {"id": "r19", "title": "Figure out outreach to all tax credit investors that will consider a ground lease structure", "status": "incomplete"},
            ],
            "Chris Aiello & Chris Andresen": [
                {"id": "r11", "title": "Finalize 3rd St Closing 4/21", "status": "complete"},
            ],
            "Chris Andresen & Robert Carrega": [
                {"id": "r2", "title": "Review the board portal for accuracy of expenses", "status": "complete"},
                {"id": "r3", "title": "Finalize Remaining Restructure Items", "status": "complete"},
                {"id": "r4", "title": "Move Investments Out of Six Peak Capital", "status": "incomplete"},
            ],
            "Derek Sanders & Grady Lakamp": [
                {"id": "r12", "title": "Francis GMP Contract Finalization & closing budget", "status": "incomplete"},
            ],
            "Derek Sanders & Tom Taggart": [
                {"id": "r14", "title": "Reading Utility bill back issue", "status": "complete"},
            ],
            "Derek Sanders (discuss with Grady)": [
                {"id": "r13", "title": "Construction photo plan", "status": "complete"},
            ],
            "Grady Lakamp & Bob Kennedy": [
                {"id": "r27", "title": "HR/401k/employees discussion", "status": "incomplete"},
            ],
            "Schuyler Dietz": [
                {"id": "r16", "title": "Create a targeted list of outbound dev. site leads", "status": "complete"},
                {"id": "r17", "title": "Finalize uplifters memo and term sheet", "status": "complete"},
                {"id": "r18", "title": "8350 Reseda HOA dialogue", "status": "complete"},
            ],
            "Schuyler Dietz & Chris Aiello": [
                {"id": "r20", "title": "Monthly Reporting to Justin Kruger", "status": "complete"},
                {"id": "r28", "title": "Revise LV website", "status": "complete"},
            ],
            "Tom Taggart": [
                {"id": "r5", "title": "Property Manager Questions and Proformas", "status": "incomplete"},
                {"id": "r6", "title": "LIHTC Parking Study", "status": "complete"},
                {"id": "r7", "title": "Reading Lease renewal plan", "status": "complete"},
            ],
        },
        "team": [],
        "todos": [
            {"id": "td_existing", "owner": "Tom Taggart", "task": "Venice Lawsuit monitoring",
             "completed": False, "source": {"type": "rock", "rock_id": "r8", "owner": "Tom Taggart"}},
        ],
    }


@pytest.fixture(scope="module")
def q3() -> dict:
    return load_json(Q3_DATA_PATH)


@pytest.fixture(scope="module")
def mig() -> dict:
    return load_json(Q3_MIGRATION_PATH)


# --- repo data files are intact -------------------------------------------

def test_in_progress_is_a_valid_status():
    assert "in_progress" in STATUSES
    assert {"complete", "incomplete"} <= STATUSES


def test_q3_data_file_shape(q3, mig):
    assert len(q3["company_rocks"]) == 7
    assert len(q3["company_rocks_deferred"]) == 1
    assert len(q3["individual_rocks"]) == 25
    assert len(mig["convert_open_old_rocks_to_todos"]) == 7
    assert len(mig["archive_done_old_rocks"]) == 15


# --- conversion ------------------------------------------------------------

def test_convert_creates_7_todos_with_owner_and_tag(q3, mig):
    data = _live_like_doc()
    data, plan = apply_migration(data, q3, mig)

    conv = [t for t in data["todos"] if (t.get("source") or {}).get("label") == "from rock (Q2)"]
    assert len(conv) == 7
    by_task = {t["task"]: t for t in conv}
    assert by_task["MRK Negotiations and finalize MOU"]["owner"] == "Bob Kennedy"
    assert by_task["Property Manager Questions and Proformas"]["owner"] == "Tom Taggart"
    assert by_task["HR/401k/employees discussion"]["owner"] == "Grady Lakamp & Bob Kennedy"
    # The pre-existing to-do is untouched (10 existing + 7 = ... here 1 + 7).
    assert any(t["id"] == "td_existing" for t in data["todos"])
    for t in conv:
        assert t["completed"] is False
        assert t["source"]["type"] == "rock"


def test_convert_archives_source_rock_not_deleted(q3, mig):
    data = _live_like_doc()
    data, _ = apply_migration(data, q3, mig)
    # r4 was a convert target — still present, now archived + converted.
    r4 = next(r for r in data["rocks"]["Chris Andresen & Robert Carrega"] if r["id"] == "r4")
    assert r4["archived"] is True
    assert r4["converted"] is True
    assert r4["quarter"] == "Q2 2026"


# --- archive ---------------------------------------------------------------

def test_archive_flags_15_none_converted(q3, mig):
    data = _live_like_doc()
    data, _ = apply_migration(data, q3, mig)
    all_rocks = list(data["company_rocks"]) + [r for v in data["rocks"].values() for r in v]
    archived_not_converted = [r for r in all_rocks
                              if r.get("archived") and not r.get("converted")]
    assert len(archived_not_converted) == 15
    # The open AI Workflow company rock is archived, not converted.
    ai = next(r for r in data["company_rocks"] if r["title"] == "AI Workflow")
    assert ai["archived"] is True and not ai.get("converted")
    # No archived-not-converted rock produced a to-do.
    cited = {(t.get("source") or {}).get("rock_id") for t in data["todos"]}
    for r in archived_not_converted:
        assert r["id"] not in cited or r["id"] == "r8"


# --- load Q3 ---------------------------------------------------------------

def test_load_q3_company_and_individual(q3, mig):
    data = _live_like_doc()
    data, _ = apply_migration(data, q3, mig)

    active_company = [r for r in data["company_rocks"]
                      if r.get("quarter") == "Q3 2026" and not r.get("deferred")]
    deferred = [r for r in data["company_rocks"] if r.get("deferred")]
    assert len(active_company) == 7
    assert len(deferred) == 1

    q3_indiv = [r for v in data["rocks"].values() for r in v
                if r.get("quarter") == "Q3 2026" and r.get("level") == "individual"]
    assert len(q3_indiv) == 25
    # Priority + done-definition populated.
    assert all(r.get("priority") in {"High", "Medium", "Low"} for r in q3_indiv)
    assert all(r.get("done_definition") for r in q3_indiv)
    # Schuyler's regulatory rock is in_progress.
    inprog = [r for r in q3_indiv if r["status"] == "in_progress"]
    assert len(inprog) == 1
    assert inprog[0]["title"].startswith("Complete all regulatory hurdles")


def test_load_q3_groups_8_owners_with_expected_counts(q3, mig):
    data = _live_like_doc()
    data, _ = apply_migration(data, q3, mig)
    groups = _group_active_by_owner(data)
    counts = {g["name"]: len(g["rocks"]) for g in groups}
    assert counts == {
        "Chris Andresen": 5, "Chris Aiello": 4, "Schuyler Dietz": 4,
        "Bob Kennedy": 2, "Robert Carrega": 3, "Derek Sanders": 3,
        "Grady Lakamp": 2, "Tom Taggart": 2,
    }
    assert sum(counts.values()) == 25
    assert len(groups) == 8


def test_company_split_and_archive_helpers(q3, mig):
    data = _live_like_doc()
    data, _ = apply_migration(data, q3, mig)
    active, deferred = _split_company_rocks(data)
    assert len(active) == 7 and len(deferred) == 1
    archive = _collect_archive(data)
    assert len(archive) == 15
    assert all(a["title"] != "" for a in archive)


# --- idempotency -----------------------------------------------------------

def test_migration_is_idempotent(q3, mig):
    data = _live_like_doc()
    data, _ = apply_migration(data, q3, mig)
    snapshot = copy.deepcopy(data)
    # Second run over the already-migrated doc must change nothing.
    data, plan2 = apply_migration(data, q3, mig)
    assert data == snapshot
    assert plan2["converted"] == [] and plan2["archived"] == []
    assert plan2["loaded_company"] == [] and plan2["loaded_individual"] == []


# --- existing rows survive the new optional fields -------------------------

def test_existing_rows_round_trip_with_new_fields(storage: Storage):
    storage.set_person_rocks("Chris", [{"id": "r1", "title": "old", "status": "incomplete"}])
    storage.add_person_rock("Chris", {
        "title": "Q3 rock", "status": "in_progress", "priority": "High",
        "done_definition": "done when shipped", "level": "individual",
        "area": "Parent", "quarter": "Q3 2026", "archived": False,
    })
    loaded = storage.load_rocks()["rocks"]["Chris"]
    assert loaded[0]["title"] == "old"            # legacy row intact
    assert loaded[1]["priority"] == "High"
    assert loaded[1]["status"] == "in_progress"
