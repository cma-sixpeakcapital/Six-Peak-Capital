from app.ingest import IngestService
from app.readai import ReadAIClient
from app.storage import Storage
from tests.conftest import FakeHttpClient, FakeSummarizer


def test_health(client) -> None:
    assert client.get("/health").get_json() == {"status": "ok"}


def test_portal_renders_empty(client) -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Level 10 Weekly" in resp.data
    assert b"No meetings ingested yet" in resp.data


def test_portal_renders_with_data(client, storage: Storage) -> None:
    storage.set_person_rocks("Chris", [{"title": "Close Acama", "status": "incomplete"}])
    storage.set_company_rocks([{"title": "Hit $10M AUM", "status": "incomplete", "due": "2026-06-30"}])
    storage.save_meeting({
        "id": "2026-04-14",
        "date": "2026-04-14",
        "title": "L10 Apr 14",
        "summary": "All good.",
        "action_items": [{"owner": "Chris", "task": "Send docs"}],
        "files": [{"name": "Acama_GMP.xlsx"}],
    })
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Close Acama" in resp.data
    assert b"Hit $10M AUM" in resp.data
    assert b"Company Rocks" in resp.data
    assert b"Individual Rocks" in resp.data
    assert b"L10 Apr 14" in resp.data
    assert b"Acama_GMP.xlsx" in resp.data


def test_meeting_detail_404_when_missing(client) -> None:
    assert client.get("/meetings/nope").status_code == 404


def test_meeting_detail_200(client, storage: Storage) -> None:
    storage.save_meeting({"id": "m1", "date": "2026-04-14", "title": "L10", "summary": "s"})
    resp = client.get("/meetings/m1")
    assert resp.status_code == 200
    assert b"s" in resp.data


def test_api_rocks_json(client, storage: Storage) -> None:
    storage.set_person_rocks("Chris", [{"title": "t", "status": "incomplete"}])
    data = client.get("/api/rocks").get_json()
    assert data["rocks"]["Chris"][0]["title"] == "t"


def test_api_update_rocks_requires_key(client) -> None:
    resp = client.put("/api/rocks/Chris", json={"rocks": []})
    assert resp.status_code == 401


def test_api_update_rocks_happy(client) -> None:
    resp = client.put(
        "/api/rocks/Chris",
        json={"rocks": [{"title": "ship", "status": "incomplete"}]},
        headers={"X-API-Key": "test-key"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["rocks"]["Chris"][0]["title"] == "ship"


def test_api_update_company_rocks_requires_key(client) -> None:
    resp = client.put("/api/company_rocks", json={"rocks": []})
    assert resp.status_code == 401


def test_api_update_company_rocks_happy(client) -> None:
    resp = client.put(
        "/api/company_rocks",
        json={"rocks": [
            {"title": "Hit $10M AUM", "status": "incomplete", "due": "2026-06-30"},
            {"title": "Launch EOS", "status": "complete"},
        ]},
        headers={"X-API-Key": "test-key"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["company_rocks"][0]["title"] == "Hit $10M AUM"


def test_api_toggle_rock_requires_key(client) -> None:
    resp = client.post("/api/rocks/r1/toggle")
    assert resp.status_code == 401


def test_api_toggle_rock_happy(client, storage: Storage) -> None:
    storage.set_person_rocks("Chris", [{"id": "r1", "title": "t", "status": "incomplete"}])
    resp = client.post("/api/rocks/r1/toggle", headers={"X-API-Key": "test-key"})
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "complete"


def test_api_toggle_rock_not_found(client) -> None:
    resp = client.post("/api/rocks/missing/toggle", headers={"X-API-Key": "test-key"})
    assert resp.status_code == 404


def test_portal_groups_by_category(client, storage: Storage) -> None:
    storage.save_rocks({
        "team": [{"name": "A"}, {"name": "B"}],
        "rocks": {
            "A": [
                {"id": "1", "title": "A-Finance-1", "status": "incomplete", "category": "Finance"},
                {"id": "2", "title": "A-Asset-1", "status": "incomplete", "category": "Asset"},
            ],
            "B": [
                {"id": "3", "title": "B-Finance-1", "status": "complete", "category": "Finance"},
            ],
        },
        "company_rocks": [],
    })
    body = client.get("/").data.decode()
    # Category headings present
    assert "Finance" in body
    assert "Asset" in body
    # Finance section should show both A and B's finance rocks
    finance_idx = body.index("Finance")
    asset_idx = body.index("Asset")
    assert finance_idx < asset_idx  # order preserved from team order (A first saw Finance)
    # The Finance rock for B must appear after the Finance header and before Asset header
    assert finance_idx < body.index("B-Finance-1") < asset_idx


def test_api_update_company_rocks_validates(client) -> None:
    resp = client.put(
        "/api/company_rocks",
        json={"rocks": [{"title": "x", "status": "nope"}]},
        headers={"X-API-Key": "test-key"},
    )
    assert resp.status_code == 400


def test_api_update_rocks_validates(client) -> None:
    resp = client.put(
        "/api/rocks/Chris",
        json={"rocks": [{"title": "x", "status": "nope"}]},
        headers={"X-API-Key": "test-key"},
    )
    assert resp.status_code == 400


def test_ingest_webhook_creates_meeting_and_runs_summarizer(client, storage: Storage) -> None:
    payload = {
        "meeting": {
            "id": "2026-04-14",
            "title": "L10 Apr 14",
            "start_time": "2026-04-14T15:00:00Z",
            "transcript_text": "Chris said ship the GMP by Thursday.",
            "participants": [{"name": "Chris"}],
        }
    }
    resp = client.post(
        "/api/ingest/readai", json=payload, headers={"X-API-Key": "test-key"}
    )
    assert resp.status_code == 200
    stored = storage.get_meeting("2026-04-14")
    assert stored is not None
    assert stored["summary"] == "Fake summary."
    assert stored["action_items"][0]["owner"] == "Chris"
    assert stored["files"][0]["name"] == "Thing.xlsx"


def test_ingest_requires_api_key(client) -> None:
    resp = client.post("/api/ingest/readai", json={"meeting": {"id": "x", "date": "2026-04-14"}})
    assert resp.status_code == 401


def test_refresh_pulls_from_readai(tmp_config) -> None:
    from app import create_app

    app = create_app(tmp_config)
    http = FakeHttpClient(payload={"meetings": [
        {"id": "new1", "date": "2026-04-14", "title": "L10", "transcript": "transcript text"}
    ]})
    storage = Storage(data_dir=tmp_config.data_dir)
    summarizer = FakeSummarizer()
    app.config["SUMMARIZER"] = summarizer
    app.config["READAI_CLIENT"] = ReadAIClient(api_key="k", http=http)
    with app.test_client() as c:
        resp = c.post("/api/refresh", headers={"X-API-Key": "test-key"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ingested"] == 1
    assert storage.get_meeting("new1") is not None


def test_refresh_skips_existing(tmp_config) -> None:
    from app import create_app

    app = create_app(tmp_config)
    storage = Storage(data_dir=tmp_config.data_dir)
    storage.save_meeting({"id": "existing", "date": "2026-04-14", "title": "seeded"})
    http = FakeHttpClient(payload={"meetings": [
        {"id": "existing", "date": "2026-04-14", "title": "L10", "transcript": "t"}
    ]})
    app.config["SUMMARIZER"] = FakeSummarizer()
    app.config["READAI_CLIENT"] = ReadAIClient(api_key="k", http=http)
    with app.test_client() as c:
        body = c.post("/api/refresh", headers={"X-API-Key": "test-key"}).get_json()
    assert body["ingested"] == 0


def test_ingest_service_skips_summarizer_when_summary_present(tmp_config) -> None:
    storage = Storage(data_dir=tmp_config.data_dir)
    summ = FakeSummarizer()
    svc = IngestService(storage=storage, summarizer=summ)
    out = svc.ingest_webhook({
        "meeting": {
            "id": "m1",
            "date": "2026-04-14",
            "summary": "already summarized",
            "action_items": [{"owner": "a", "task": "b"}],
            "transcript": "raw",
        }
    })
    assert out["summary"] == "already summarized"
    assert summ.calls == []
