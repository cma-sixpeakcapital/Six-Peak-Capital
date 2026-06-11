from app.config import Config
from app.ingest import IngestService
from app.storage import Storage
from tests.conftest import FakeSummarizer

# The live default pattern (no INGEST_TITLE_PATTERN env override for L10).
_DEFAULT_PATTERN = Config.ingest_title_pattern


def _svc(storage: Storage, pattern: str) -> IngestService:
    return IngestService(storage=storage, summarizer=FakeSummarizer(), title_pattern=pattern)


def test_title_matches_default_patterns(storage: Storage) -> None:
    svc = _svc(storage, r"(?i)\bL10\b|Weekly Six Peak|Level 10|Leadership")
    assert svc.title_matches("L10 Week of Apr 14")
    assert svc.title_matches("Weekly Six Peak Capital Call")
    assert svc.title_matches("Level 10 — Leadership")
    assert svc.title_matches("Leadership Sync")
    assert not svc.title_matches("Sales call with Acme")
    assert not svc.title_matches("1:1 Chris / Bob")
    assert not svc.title_matches("")


def test_default_pattern_matches_rock_session(storage: Storage) -> None:
    """Quarterly EOS Rock Sessions ingest via the same default title filter as
    the weekly L10 — no per-quarter config change needed."""
    svc = _svc(storage, _DEFAULT_PATTERN)
    assert svc.title_matches("Six Peak EOS — Q3 2026 Rock Session")
    assert svc.title_matches("Six Peak EOS — Q4 2026 Rock Session")
    assert svc.title_matches("Quarterly Rock Session")
    # Weekly L10 still matches.
    assert svc.title_matches("Six Peak Capital - Weekly L10")
    # Unrelated meetings still ignored.
    assert not svc.title_matches("Sales call with Acme")


def test_ingest_stamps_rock_session_kind(storage: Storage) -> None:
    svc = _svc(storage, _DEFAULT_PATTERN)
    svc.ingest_webhook({"meeting": {
        "id": "rs1", "date": "2026-06-11",
        "title": "Six Peak EOS — Q3 2026 Rock Session",
    }})
    assert storage.get_meeting("rs1")["kind"] == "rock_session"


def test_ingest_stamps_l10_kind(storage: Storage) -> None:
    svc = _svc(storage, _DEFAULT_PATTERN)
    svc.ingest_webhook({"meeting": {
        "id": "w1", "date": "2026-06-09", "title": "Six Peak Capital - Weekly L10",
    }})
    assert storage.get_meeting("w1")["kind"] == "l10"


def test_empty_pattern_accepts_all(storage: Storage) -> None:
    svc = _svc(storage, "")
    assert svc.title_matches("Anything goes")
    assert svc.title_matches("")


def test_invalid_pattern_fails_open(storage: Storage) -> None:
    svc = _svc(storage, "[unclosed")
    assert svc.title_matches("anything")


def test_ingest_webhook_persists_when_matching(storage: Storage) -> None:
    svc = _svc(storage, r"(?i)L10")
    result = svc.ingest_webhook({"meeting": {"id": "m1", "date": "2026-04-14", "title": "L10 Weekly"}})
    assert result["id"] == "m1"
    assert storage.get_meeting("m1") is not None


def test_ingest_webhook_ignores_non_matching(storage: Storage) -> None:
    svc = _svc(storage, r"(?i)L10")
    result = svc.ingest_webhook({"meeting": {"id": "skip", "date": "2026-04-14", "title": "Sales"}})
    assert result["status"] == "ignored"
    assert result["reason"] == "title_filter"
    assert storage.get_meeting("skip") is None


def test_refresh_skips_non_matching(storage: Storage) -> None:
    from app.readai import ReadAIClient
    from tests.conftest import FakeHttpClient

    http = FakeHttpClient(payload={"meetings": [
        {"id": "keep", "date": "2026-04-14", "title": "L10 Apr"},
        {"id": "drop", "date": "2026-04-14", "title": "Random Sales Sync"},
    ]})
    svc = IngestService(
        storage=storage,
        summarizer=FakeSummarizer(),
        readai=ReadAIClient(api_key="k", http=http),
        title_pattern=r"(?i)L10",
    )
    saved = svc.refresh_from_readai()
    ids = [m["id"] for m in saved]
    assert "keep" in ids
    assert "drop" not in ids
