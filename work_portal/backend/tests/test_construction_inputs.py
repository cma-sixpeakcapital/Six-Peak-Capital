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
    assert "Bob" in doc["notice"] and "Grady" in doc["notice"]


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
    assert "Temporary note" in html


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
        html = c.get("/").get_data(as_text=True)
        assert "Temporary note" not in html
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
