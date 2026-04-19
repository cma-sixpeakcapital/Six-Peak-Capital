import pytest

from app.readai import ReadAIClient, _normalize
from tests.conftest import FakeHttpClient


def test_normalize_basic() -> None:
    raw = {
        "id": "abc",
        "title": "L10",
        "start_time": "2026-04-14T15:00:00Z",
        "participants": [{"name": "Chris"}, {"name": "Ana"}],
        "transcript_text": "...",
    }
    out = _normalize(raw)
    assert out["id"] == "abc"
    assert out["date"] == "2026-04-14"
    assert out["attendees"] == ["Chris", "Ana"]
    assert out["transcript"] == "..."
    assert out["action_items"] == []


def test_normalize_handles_string_attendees() -> None:
    out = _normalize({"id": "x", "date": "2026-04-14", "attendees": ["Chris", "Ana"]})
    assert out["attendees"] == ["Chris", "Ana"]


def test_list_recent_meetings_happy_path() -> None:
    http = FakeHttpClient(payload={"meetings": [
        {"id": "m1", "title": "L10 A", "date": "2026-04-14", "transcript": "..."},
    ]})
    client = ReadAIClient(api_key="k", http=http)
    meetings = client.list_recent_meetings()
    assert len(meetings) == 1
    assert meetings[0]["id"] == "m1"
    assert "Authorization" in http.calls[0]["headers"]
    assert http.calls[0]["params"]["tag"] == "L10"


def test_list_recent_meetings_requires_key() -> None:
    client = ReadAIClient(api_key="")
    with pytest.raises(RuntimeError):
        client.list_recent_meetings()


def test_list_recent_meetings_handles_api_error() -> None:
    http = FakeHttpClient(payload={}, status_code=500)
    client = ReadAIClient(api_key="k", http=http)
    with pytest.raises(RuntimeError, match="500"):
        client.list_recent_meetings()


def test_list_recent_meetings_handles_list_payload() -> None:
    http = FakeHttpClient(payload=[{"id": "m1", "date": "2026-04-14"}])
    client = ReadAIClient(api_key="k", http=http)
    meetings = client.list_recent_meetings()
    assert meetings[0]["id"] == "m1"
