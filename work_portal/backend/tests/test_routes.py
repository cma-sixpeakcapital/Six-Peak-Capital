from datetime import datetime, timedelta, timezone

from app import create_app
from app.config import Config
from app.ingest import IngestService
from app.readai import ReadAIClient
from app.storage import Storage
from tests.conftest import FakeHttpClient, FakeSummarizer


def test_health(client) -> None:
    assert client.get("/health").get_json() == {"status": "ok"}


# --- Job endpoint: non-consuming preview wiring --------------------------
# Proves the ?preview=true route resolves recipients into would_send and
# writes nothing to the DB — the portable equivalent of the spec's gunicorn
# preview check (gunicorn is Unix-only and there's no local Postgres).


class _FakeCalExec:
    def __init__(self, result):
        self._result = result

    def execute(self):
        return self._result


class _FakeCalendar:
    """Minimal events().instances()/list() stub returning one attendee."""

    def __init__(self, emails):
        self._items = [{
            "status": "confirmed",
            "attendees": [{"email": e, "responseStatus": "accepted"} for e in emails],
        }]

    def events(self):
        return self

    def instances(self, **kwargs):
        return _FakeCalExec({"items": self._items})

    def list(self, **kwargs):
        return _FakeCalExec({"items": self._items})


def _followup_config(tmp_path) -> Config:
    data_dir = tmp_path / "data"
    (data_dir / "meetings").mkdir(parents=True, exist_ok=True)
    return Config(
        data_dir=data_dir,
        secret_key="t",
        api_key="test-key",
        anthropic_api_key="",
        readai_api_key="",
        followup_sender_email="cma@sixpeakcapital.com",
        followup_cal_event_id="evt_recurring",
        followup_subject_prefix="L10 Follow-up",
        followup_portal_name="L10 Weekly",
        followup_portal_url="https://l10.sixpeakapps.com",
        followup_cadence="weekly",
    )


def test_send_followups_preview_route_lists_recipients_without_consuming(tmp_path) -> None:
    cfg = _followup_config(tmp_path)
    app = create_app(cfg)
    app.config["FOLLOWUPS_CALENDAR_SERVICE"] = _FakeCalendar(["rak@sixpeakcapital.com"])
    storage = app.config["STORAGE"]
    saved_at = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    storage.save_meeting({
        "id": "2026-04-28", "date": "2026-04-28",
        "title": "Six Peak Capital - Weekly L10",
        "summary": "A. B. C.", "action_items": [], "saved_at": saved_at,
    })

    with app.test_client() as c:
        resp = c.post("/api/jobs/send_followups?preview=true",
                      headers={"X-API-Key": "test-key"})
    body = resp.get_json()

    assert resp.status_code == 200
    assert body["preview"] is True
    assert body["sent"] == [] and body["drafts"] == []
    assert [w["meeting_id"] for w in body["would_send"]] == ["2026-04-28"]
    assert body["would_send"][0]["recipients"] == ["rak@sixpeakcapital.com"]
    # No DB write: the meeting is untouched and still pending.
    assert storage.get_meeting("2026-04-28").get("_followup_sent_at") is None
    assert any(m["id"] == "2026-04-28"
               for m in storage.list_meetings_pending_followup(min_age_hours=24, max_age_days=7))


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


def test_api_update_rocks_happy(client) -> None:
    resp = client.put(
        "/api/rocks/Chris",
        json={"rocks": [{"title": "ship", "status": "incomplete"}]},
        headers={"X-API-Key": "test-key"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["rocks"]["Chris"][0]["title"] == "ship"


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


def test_api_toggle_rock_happy(client, storage: Storage) -> None:
    storage.set_person_rocks("Chris", [{"id": "r1", "title": "t", "status": "incomplete"}])
    resp = client.post("/api/rocks/r1/toggle", headers={"X-API-Key": "test-key"})
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "complete"


def test_api_toggle_rock_not_found(client) -> None:
    resp = client.post("/api/rocks/missing/toggle", headers={"X-API-Key": "test-key"})
    assert resp.status_code == 404


def test_portal_groups_by_owner(client, storage: Storage) -> None:
    # Q3-style set: individual rocks grouped by owner, archived excluded from
    # active cards and surfaced in "Past quarters"; deferred company rock in
    # its own collapsed subsection.
    storage.save_rocks({
        "team": [],
        "rocks": {
            "Zoe Owner": [
                {"id": "1", "title": "Zoe-Active-1", "status": "incomplete",
                 "level": "individual", "priority": "High", "quarter": "Q3 2026"},
            ],
            "Amy Owner": [
                {"id": "2", "title": "Amy-Active-1", "status": "in_progress",
                 "level": "individual", "priority": "Medium", "quarter": "Q3 2026"},
                {"id": "3", "title": "Amy-Archived-Old", "status": "complete",
                 "archived": True, "quarter": "Q2 2026"},
            ],
        },
        "company_rocks": [
            {"id": "c1", "title": "Co-Active", "status": "incomplete", "level": "company",
             "owner": "Amy Owner", "priority": "High", "quarter": "Q3 2026"},
            {"id": "c2", "title": "Co-Deferred", "status": "incomplete", "level": "company",
             "deferred": True, "quarter": "Q3 2026"},
        ],
    })
    body = client.get("/").data.decode()
    assert "By owner" in body
    # Owners alphabetical: Amy before Zoe.
    assert body.index("Amy Owner") < body.index("Zoe Owner")
    assert "Amy-Active-1" in body and "Zoe-Active-1" in body
    # Priority badge + in-progress pill rendered.
    assert "prio-high" in body and "prio-medium" in body
    assert "status-progress" in body
    # Deferred company rock surfaced in its own subsection, not the active list.
    assert "Co-Deferred" in body and "Deferred / Q4" in body
    # Archived old rock lands in Past quarters, not an active owner card.
    assert "Past quarters" in body
    assert "Amy-Archived-Old" in body
    # Archived rock must not carry the active .rock class (KPI counts only active).
    assert 'class="rock rock-complete"' not in body
    # Company rock shows its accountable owner in the Company section.
    assert "rock-owner" in body
    # Amy owns a company rock → her card carries a checkable reference to it
    # (same rock id, but a .rock-ref so the KPI doesn't double-count it).
    assert "Company Rock owned" in body
    assert 'class="rock-ref rock-incomplete" data-rock-id="c1"' in body
    # The full company rock (the .rock li) exists once in the Company section;
    # the reference is a separate .rock-ref so the KPI doesn't double-count it.
    assert 'class="rock rock-incomplete" data-rock-id="c1"' in body


def test_owner_with_only_company_rock_gets_a_card(client, storage: Storage) -> None:
    # An owner who owns a company rock but has no individual rocks still gets a
    # card (with the checkable reference), so accountability is never hidden.
    storage.save_rocks({
        "team": [],
        "rocks": {},
        "company_rocks": [
            {"id": "c9", "title": "Solo-Co-Rock", "status": "incomplete", "level": "company",
             "owner": "Pat Lead", "priority": "High", "quarter": "Q3 2026"},
        ],
    })
    body = client.get("/").data.decode()
    assert "Pat Lead" in body
    assert 'data-rock-id="c9"' in body
    assert "Company Rock owned" in body


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


def test_ingest_filters_non_matching_titles(client, storage) -> None:
    payload = {
        "meeting": {
            "id": "offtopic-1",
            "title": "Internal Sales Call — Acme Corp",
            "date": "2026-04-14",
        }
    }
    resp = client.post(
        "/api/ingest/readai", json=payload, headers={"X-API-Key": "test-key"}
    )
    # 200 so Read.ai doesn't retry; body signals ignored
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "ignored"
    assert body["reason"] == "title_filter"
    # Not persisted
    assert storage.get_meeting("offtopic-1") is None


def test_ingest_accepts_matching_titles(client, storage) -> None:
    payload = {
        "meeting": {
            "id": "l10-ok",
            "title": "Weekly Six Peak Capital Call",
            "start_time": "2026-04-14T15:00:00Z",
            "transcript_text": "...",
        }
    }
    resp = client.post(
        "/api/ingest/readai", json=payload, headers={"X-API-Key": "test-key"}
    )
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"
    assert storage.get_meeting("l10-ok") is not None


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
