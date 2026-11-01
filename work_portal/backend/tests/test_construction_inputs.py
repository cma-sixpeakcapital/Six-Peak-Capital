"""Construction inputs: the human-entered numbers behind Grady's GC scorecard
(contract dates, cause codes, contingency notes, utilization hours), entered on
the portal and read by the Monday feed."""
from datetime import date

import pytest

from app import create_app
from app.construction import (DEFAULT_ROLES, SEED_SOURCE, default_doc, get_doc, set_jobs,
                              set_utilization, utilization_summary)


def test_default_doc_seeds_jobs_with_benchmark_standins():
    doc = default_doc()
    jobs = {j["job"]: j for j in doc["jobs"]}
    assert set(jobs) >= {"Whipple", "Califa", "Nelrose", "Ramsgate", "Crenshaw", "Riverton",
                         "Lexington", "Francis", "Acama"}
    assert jobs["Whipple"]["contract_completion"] == "2027-08-30"
    assert jobs["Whipple"]["contract_source"] == SEED_SOURCE
    assert jobs["Acama"]["contract_completion"] == "" and jobs["Acama"]["contract_source"] == ""
    assert doc["roles"] == DEFAULT_ROLES
    assert [n["to"] for n in doc["notices"]] == ["Bob", "Chris Andresen", "Tom", "Grady"]
    assert jobs["Whipple"]["client"] == "HVN" and jobs["Francis"]["client"] == "Six Peak affiliate"
    assert jobs["Riverton"]["client"] == "" and doc["clients_pending"]["Klump"] == "Third party"
    assert doc["awards"] == []
    assert doc["notice"] == ""


def test_old_single_notice_migrates_to_per_person_notes():
    from app.construction import remove_notice
    data = {"construction_inputs": {"jobs": [], "roles": DEFAULT_ROLES, "utilization": {}, "notice": "old combined note"}}
    doc = get_doc(data)
    assert [n["id"] for n in doc["notices"]] == ["bob", "chris-andresen", "tom", "grady"] and doc["notice"] == ""
    assert remove_notice(doc, "bob") and [n["id"] for n in doc["notices"]] == ["chris-andresen", "tom", "grady"]
    assert not remove_notice(doc, "bob")
    # a doc whose note was already cleared gets no notes back
    assert get_doc({"construction_inputs": {"jobs": [], "roles": [], "utilization": {}, "notice": ""}})["notices"] == []


def test_backlog_migration_and_awards():
    from app.construction import set_awards
    # a live doc from the 10/31 deploy: no client flags, no awards, three notes
    data = {"construction_inputs": {"jobs": [{"job": "Whipple", "active": True}, {"job": "NewJob", "active": True}],
                                    "roles": DEFAULT_ROLES, "utilization": {}, "notice": "",
                                    "notices": [{"id": "bob", "to": "Bob", "text": "x"}]}}
    doc = get_doc(data)
    assert doc["jobs"][0]["client"] == "HVN" and doc["jobs"][1]["client"] == ""
    assert doc["clients_pending"]["Troost"] == "HVN"
    assert [n["id"] for n in doc["notices"]] == ["bob", "tom"]   # Tom's note added once
    assert [n["id"] for n in get_doc(data)["notices"]] == ["bob", "tom"]
    set_awards(doc, [{"project": "Moorpark", "client": "Kinfolk", "award_date": "2026-10-28",
                      "expected_value": "18,500,000", "expected_signing": "2027-01-15", "status": "awarded"},
                     {"project": "", "expected_value": 5}])
    assert doc["awards"] == [{"project": "Moorpark", "client": "Kinfolk", "award_date": "2026-10-28",
                              "expected_value": 18500000.0, "expected_signing": "2027-01-15", "kpi_job": "",
                              "status": "awarded", "notes": ""}]
    with pytest.raises(ValueError):
        set_awards(doc, [{"project": "X", "status": "maybe"}])
    with pytest.raises(ValueError):
        set_awards(doc, [{"project": "X", "expected_value": "lots"}])
    with pytest.raises(ValueError):
        set_jobs(doc, [{"job": "Whipple", "client": "Owner"}])


def test_set_jobs_validates():
    doc = default_doc()
    set_jobs(doc, [{"job": "Whipple", "contract_completion": "2027-09-15",
                    "contract_source": "Pay app #14", "cause_code": "owner"}],
             roles=["Superintendent", "Project Manager"])
    assert doc["jobs"][0]["contract_completion"] == "2027-09-15"
    assert doc["roles"] == ["Superintendent", "Project Manager"]
    with pytest.raises(ValueError):
        set_jobs(doc, [{"job": "Whipple", "contract_completion": "next spring"}])
    with pytest.raises(ValueError):
        set_jobs(doc, [{"job": "Whipple", "cause_code": "gremlins"}])
    with pytest.raises(ValueError):
        set_jobs(doc, [{"job": "Whipple"}, {"job": "whipple"}])
    with pytest.raises(ValueError):
        set_jobs(doc, [{"job": "Whipple"}], roles=[])


def test_utilization_math_matches_the_feed_rule():
    doc = default_doc()
    set_utilization(doc, "2026-11", {
        "Whipple": {"Superintendent": 160, "Project Manager": 60},
        "Califa": {"Superintendent": 160, "Project Manager": 60, "Assistant PM": 40},
        "Nelrose": {"Superintendent": 80, "Project Manager": 60},
    }, [
        {"person": "Super A", "role": "Superintendent", "hours": 152},
        {"person": "Super B", "role": "Superintendent", "hours": 152},
        {"person": "Super C", "role": "superintendent", "hours": 160},   # case-insensitive role
        {"person": "Pedro Rosales", "role": "Project Manager", "hours": 152},
        {"person": "", "role": "Project Manager", "hours": 152},          # blank person ignored
        {"person": "APM", "role": "Assistant PM", "hours": 152},
    ], note="first read")
    s = utilization_summary(doc, "2026-11")
    by = {r["role"]: r for r in s["roles"]}
    assert by["Superintendent"]["pct"] == round(100 * 400 / 464)   # 86
    assert by["Project Manager"]["pct"] == round(100 * 180 / 152)  # 118
    assert by["Assistant PM"]["pct"] == round(100 * 40 / 152)      # 26
    assert by["Project Coordinator"]["pct"] is None                # no hours either side
    assert s["highest"] == {"role": "Project Manager", "pct": 118}
    assert utilization_summary(doc, "2026-12") is None
    with pytest.raises(ValueError):
        set_utilization(doc, "Nov 2026", {}, [])
    with pytest.raises(ValueError):
        set_utilization(doc, "2026-11", {"Not A Job": {"Superintendent": 10}}, [])
    with pytest.raises(ValueError):
        set_utilization(doc, "2026-11", {"Whipple": {"Janitor": 10}}, [])


@pytest.fixture
def ci_app(tmp_config):
    return create_app(tmp_config)


def test_page_shows_construction_section_and_nav(ci_app):
    with ci_app.test_client() as c:
        html = c.get("/").get_data(as_text=True)
    assert 'id="construction"' in html
    assert "#construction" in html
    assert "benchmark (pending pay app)" in html
    assert "Note for Bob" in html and "Note for Chris Andresen" in html and "Note for Grady" in html


def test_api_roundtrip_and_audit(ci_app):
    with ci_app.test_client() as c:
        r = c.get("/api/construction_inputs")
        assert r.status_code == 200
        body = r.get_json()
        assert body["roles"] == DEFAULT_ROLES and body["utilization"] == {}
        jobs = body["jobs"]
        jobs[0]["contract_completion"] = "2027-09-15"
        jobs[0]["contract_source"] = "Pay app #14"
        jobs[0]["cause_code"] = "weather"
        r = c.put("/api/construction_inputs/jobs", json={"jobs": jobs, "roles": DEFAULT_ROLES + ["Laborer"]},
                  headers={"X-Actor": "Chris Andresen"})
        assert r.status_code == 200, r.get_data(as_text=True)
        assert r.get_json()["roles"][-1] == "Laborer"
        r = c.put("/api/construction_inputs/utilization/2026-11", json={
            "required": {jobs[0]["job"]: {"Laborer": 100}},
            "available": [{"person": "Crew", "role": "Laborer", "hours": 120}], "note": "n"},
            headers={"X-Actor": "Grady Lakamp"})
        assert r.status_code == 200, r.get_data(as_text=True)
        assert r.get_json()["summary"]["highest"] == {"role": "Laborer", "pct": 83}
        assert c.put("/api/construction_inputs/utilization/nov", json={}).status_code == 400
        assert c.put("/api/construction_inputs/jobs", json={"jobs": "x"}).status_code == 400
        r = c.put("/api/construction_inputs/notice", json={"text": ""}, headers={"X-Actor": "Chris Aiello"})
        assert r.get_json()["notice"] == ""
        feed = c.get("/api/construction_inputs").get_json()
        assert feed["jobs"][0]["contract_completion"] == "2027-09-15"
        assert feed["utilization"]["2026-11"]["highest"]["pct"] == 83
        assert feed["notice"] == ""
        r = c.put("/api/construction_inputs/awards", json={"awards": [
            {"project": "Moorpark", "expected_value": 18500000, "status": "awarded"}]}, headers={"X-Actor": "Tom Taggart"})
        assert r.status_code == 200 and r.get_json()["awards"][0]["expected_value"] == 18500000
        assert c.put("/api/construction_inputs/awards", json={"awards": "x"}).status_code == 400
        assert c.get("/api/construction_inputs").get_json()["awards"][0]["project"] == "Moorpark"
        # per-person note: rewrite Grady's, add one for Kim, paragraphs render separately
        r = c.put("/api/construction_inputs/notices/grady", json={"text": "First para.\n\nSecond para."},
                  headers={"X-Actor": "Chris Aiello"})
        assert r.status_code == 200 and r.get_json() == {"id": "grady", "to": "Grady", "text": "First para.\n\nSecond para."}
        r = c.put("/api/construction_inputs/notices/kim", json={"to": "Kim", "text": "Contract dates please."})
        assert r.status_code == 200 and r.get_json()["to"] == "Kim"
        assert c.put("/api/construction_inputs/notices/kim", json={"text": ""}).status_code == 400
        html = c.get("/").get_data(as_text=True)
        assert "<p>First para.</p><p>Second para.</p>" in html and "Note for Kim" in html
        assert [n["id"] for n in c.get("/api/construction_inputs").get_json()["notices"]][-2:] == ["grady", "kim"]
        r = c.delete("/api/construction_inputs/notices/grady", headers={"X-Actor": "Grady Lakamp"})
        assert r.status_code == 200
        assert c.delete("/api/construction_inputs/notices/grady").status_code == 404
        html = c.get("/").get_data(as_text=True)
        assert "Note for Grady" not in html and "Note for Bob" in html
    storage = ci_app.config["STORAGE"]
    audit = storage.list_audit(limit=10)
    actions = {a["action"] for a in audit}
    assert "Edit construction inputs (jobs / roles)" in actions
    assert "Edit construction utilization hours" in actions
    jobs_edit = next(a for a in audit if a["action"] == "Edit construction inputs (jobs / roles)")
    assert jobs_edit["actor"] == "Chris Andresen"
    items = {ch["item"] for ch in jobs_edit["changes"]}
    assert any(i.startswith("cjob:") for i in items) and "doc:construction_roles" in items
    # history / restore still works: the doc is inside the rocks document
    assert get_doc(storage.load_rocks())["jobs"][0]["cause_code"] == "weather"
    assert storage.list_rocks_history(limit=5)
