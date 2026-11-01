"""V/TO and Accountability Chart sections (off-site to-dos, 11/1/2026)."""
import pytest

from app import create_app
from app.vto import SEED_CHART, SEED_VTO, get_doc, mark_reviewed, set_chart, set_vto


def test_seed_matches_redline_and_session_changes():
    doc = get_doc({})
    v, c = doc["vto"], doc["chart"]
    assert len(v["core_values"]) == 6 and v["core_values"][0] == "Radical transparency and alignment"
    assert "California" in v["niche"] and "docs.google.com" in v["doc_url"]
    seats = {s["seat"]: s for s in c["seats"]}
    assert "Integrator + LV Interface (one consolidated seat)" in seats          # Bob: one seat for Chris
    assert any("LV expansion / acquisition" in r for r in seats["Visionary"]["roles"])
    assert any("Board portal, Steyn reporting" in r for r in seats["CFO"]["roles"])
    assert not any("Board portal" in r for r in seats["Integrator + LV Interface (one consolidated seat)"]["roles"])
    assert any("Development management consulting" in r for r in seats["Development"]["roles"])
    assert any("pay-app automation" in r for r in seats["Accounting (reports to CFO)"]["roles"])
    assert c["reviews"] == []


def test_set_vto_and_chart_validate():
    doc = get_doc({})
    set_vto(doc, {**SEED_VTO, "core_values": "A\nB\n\nC", "say_no_to": ["x"], "marketing": [{"label": "Target", "text": "t"}, {"label": "", "text": "dropped"}]})
    assert doc["vto"]["core_values"] == ["A", "B", "C"] and doc["vto"]["marketing"] == [{"label": "Target", "text": "t"}]
    with pytest.raises(ValueError):
        set_vto(doc, {**SEED_VTO, "core_values": []})
    with pytest.raises(ValueError):
        set_vto(doc, {**SEED_VTO, "doc_url": "http://insecure"})
    set_chart(doc, {"as_of": "test", "seats": [{"seat": "CFO", "person": "CA", "roles": "a\nb", "gwc": "Y / Y / Y", "flag": ""}, {"seat": "", "person": "x"}],
                    "proposed_changes": "p1\np2"})
    assert len(doc["chart"]["seats"]) == 1 and doc["chart"]["seats"][0]["roles"] == ["a", "b"]
    assert doc["chart"]["proposed_changes"] == ["p1", "p2"]
    with pytest.raises(ValueError):
        set_chart(doc, {"seats": []})
    e = mark_reviewed(doc, "Chris Aiello", "Q4 2026")
    assert e["quarter"] == "Q4 2026" and doc["chart"]["reviews"][-1]["by"] == "Chris Aiello"


@pytest.fixture
def vto_app(tmp_config):
    return create_app(tmp_config)


def test_page_and_api(vto_app):
    with vto_app.test_client() as c:
        html = c.get("/").get_data(as_text=True)
        assert 'id="vto"' in html and 'id="chart"' in html and "#vto" in html and "#chart" in html
        assert "Radical transparency and alignment" in html and "Integrator + LV Interface" in html
        assert "Not yet reviewed on the portal" in html
        d = c.get("/api/vto").get_json()
        assert len(d["vto"]["core_values"]) == 6
        body = dict(SEED_VTO); body["ten_year_date"] = "December 31, 2036"
        r = c.put("/api/vto", json=body, headers={"X-Actor": "Bob Kennedy"})
        assert r.status_code == 200 and r.get_json()["ten_year_date"] == "December 31, 2036"
        assert c.put("/api/vto", json={"core_values": []}).status_code == 400
        chart = dict(SEED_CHART); chart["seats"] = chart["seats"][:2]
        r = c.put("/api/vto/chart", json=chart, headers={"X-Actor": "Bob Kennedy"})
        assert r.status_code == 200 and len(r.get_json()["seats"]) == 2
        r = c.post("/api/vto/chart/reviewed", json={"quarter": "Q4 2026"}, headers={"X-Actor": "Chris Aiello"})
        assert r.status_code == 200 and r.get_json()["by"] == "Chris Aiello"
        html = c.get("/").get_data(as_text=True)
        assert "Last reviewed <b>Q4 2026</b>" in html
    actions = {a["action"] for a in vto_app.config["STORAGE"].list_audit(limit=10)}
    assert {"Edit V/TO", "Edit Accountability Chart", "Mark Accountability Chart reviewed"} <= actions
