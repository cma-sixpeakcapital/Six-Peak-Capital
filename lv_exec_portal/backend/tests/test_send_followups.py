"""Tests for the follow-up email job.

Uses the file-backed Storage and fake Gmail/Calendar services so we don't
need a Postgres or Google credentials to run.
"""
from __future__ import annotations

import base64
import email
import email.policy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from app.config import Config
from app.jobs.send_followups import run, lookup_invitees
from app.jobs.email_template import render_email
from app.storage import Storage


# --- Fakes ---------------------------------------------------------------


class FakeGmail:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.created_drafts: list[dict[str, Any]] = []
        self.fail_on_send = False

    def users(self):
        return self

    def messages(self):
        return self

    def drafts(self):
        return _DraftsHandle(self)

    def send(self, *, userId: str, body: dict[str, Any]):
        return _Exec(self._do_send, body)

    def _do_send(self, body: dict[str, Any]):
        if self.fail_on_send:
            raise RuntimeError("simulated Gmail outage")
        self.sent.append(_decode_raw(body["raw"]))
        return {"id": f"msg_{len(self.sent)}"}


class _DraftsHandle:
    def __init__(self, parent: "FakeGmail") -> None:
        self.parent = parent

    def create(self, *, userId: str, body: dict[str, Any]):
        return _Exec(self._do_create, body)

    def _do_create(self, body: dict[str, Any]):
        msg = body["message"]
        self.parent.created_drafts.append(_decode_raw(msg["raw"]))
        return {"id": f"draft_{len(self.parent.created_drafts)}"}


class _Exec:
    def __init__(self, fn, *args) -> None:
        self.fn = fn
        self.args = args

    def execute(self) -> Any:
        return self.fn(*self.args)


def _decode_raw(raw_b64: str) -> dict[str, Any]:
    raw_bytes = base64.urlsafe_b64decode(raw_b64.encode("ascii"))
    msg = email.message_from_bytes(raw_bytes, policy=email.policy.default)
    parts: dict[str, str] = {}
    for part in msg.walk():
        ctype = part.get_content_type()
        if ctype in ("text/plain", "text/html"):
            content = part.get_content()
            if isinstance(content, bytes):
                content = content.decode("utf-8", errors="replace")
            parts[ctype] = content
    return {
        "from": str(msg["From"] or ""),
        "to": str(msg["To"] or ""),
        "subject": str(msg["Subject"] or ""),
        "text": parts.get("text/plain", ""),
        "html": parts.get("text/html", ""),
    }


class FakeCalendar:
    """Returns a configurable list of attendees for events.instances() calls."""
    def __init__(self, attendees: list[dict[str, Any]] | None = None,
                 raise_error: Exception | None = None,
                 return_empty: bool = False) -> None:
        self.attendees = attendees or []
        self.raise_error = raise_error
        self.return_empty = return_empty
        self.calls: list[dict[str, Any]] = []

    def events(self):
        return self

    def instances(self, **kwargs):
        self.calls.append(kwargs)
        return _Exec(self._return_instance)

    def _return_instance(self) -> dict[str, Any]:
        if self.raise_error:
            raise self.raise_error
        if self.return_empty:
            return {"items": []}
        return {"items": [{"status": "confirmed", "attendees": self.attendees}]}


# --- Fixtures ------------------------------------------------------------


@pytest.fixture
def storage(tmp_path: Path) -> Storage:
    data_dir = tmp_path / "data"
    (data_dir / "meetings").mkdir(parents=True, exist_ok=True)
    return Storage(data_dir=data_dir)


@pytest.fixture
def cfg(tmp_path: Path) -> Config:
    return Config(
        data_dir=tmp_path / "data",
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


def _saved_at(hours_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


def _make_meeting(storage: Storage, *, hours_ago: float, summary: str = "A. B. C.",
                  meeting_id: str = "2026-04-28", date: str = "2026-04-28",
                  action_items: list | None = None) -> dict[str, Any]:
    storage.save_meeting({
        "id": meeting_id,
        "date": date,
        "title": "Six Peak Capital - Weekly L10",
        "summary": summary,
        "action_items": action_items or [],
        "saved_at": _saved_at(hours_ago),
    })
    return storage.get_meeting(meeting_id) or {}


def _calendar_with(emails: list[str]) -> FakeCalendar:
    return FakeCalendar(attendees=[{"email": e, "responseStatus": "accepted"} for e in emails])


# --- Tests --------------------------------------------------------------


def test_template_handles_empty_action_items(cfg):
    meeting = {"id": "x", "date": "2026-04-28", "title": "L10",
               "summary": "Foo. Bar.", "action_items": []}
    subject, html, text = render_email(
        meeting, [], subject_prefix=cfg.followup_subject_prefix,
        portal_name=cfg.followup_portal_name, portal_url=cfg.followup_portal_url,
        cadence=cfg.followup_cadence,
    )
    assert "L10 Follow-up — 2026-04-28 (L10)" in subject
    assert "(no action items from this meeting)" in html
    assert "(no action items from this meeting)" in text


def test_template_handles_empty_owner(cfg):
    meeting = {"id": "x", "date": "2026-04-28", "summary": "S.",
               "action_items": [{"id": "a1", "owner": "", "task": "Do something"}]}
    subject, html, text = render_email(
        meeting, [], subject_prefix=cfg.followup_subject_prefix,
        portal_name=cfg.followup_portal_name, portal_url=cfg.followup_portal_url,
        cadence=cfg.followup_cadence,
    )
    assert "Unassigned" in html
    assert "Unassigned" in text


def test_template_handles_empty_due(cfg):
    meeting = {"id": "x", "date": "2026-04-28", "summary": "S.", "action_items": []}
    todos = [{"owner": "Bob", "task": "Do thing", "due": ""}]
    subject, html, text = render_email(
        meeting, todos, subject_prefix=cfg.followup_subject_prefix,
        portal_name=cfg.followup_portal_name, portal_url=cfg.followup_portal_url,
        cadence=cfg.followup_cadence,
    )
    # Task rendered, no parenthetical
    assert "Do thing" in text
    assert "Do thing (" not in text


def test_template_groups_todos_by_owner(cfg):
    meeting = {"id": "x", "date": "2026-04-28", "summary": "S.", "action_items": []}
    todos = [
        {"owner": "Bob", "task": "B-task-1"},
        {"owner": "Alice", "task": "A-task"},
        {"owner": "Bob", "task": "B-task-2"},
    ]
    _, html, text = render_email(
        meeting, todos, subject_prefix=cfg.followup_subject_prefix,
        portal_name=cfg.followup_portal_name, portal_url=cfg.followup_portal_url,
        cadence=cfg.followup_cadence,
    )
    # Alice comes before Bob (case-insensitive sort); Bob's two tasks under one heading
    assert text.index("Alice") < text.index("Bob")
    assert text.count("Bob") == 1  # one owner heading
    assert "B-task-1" in text and "B-task-2" in text


def test_cycle_word_per_cadence(cfg):
    meeting = {"id": "x", "date": "2026-04-28", "summary": "S.", "action_items": []}
    for cadence, word in [("weekly", "WEEK"), ("biweekly", "CYCLE"), ("monthly", "MONTH")]:
        _, _, text = render_email(
            meeting, [], subject_prefix="P", portal_name="N",
            portal_url="https://x", cadence=cadence,
        )
        assert f"NEXT {word}" in text


# Storage / pending list


def test_skips_meeting_when_summary_blank(storage, cfg):
    _make_meeting(storage, hours_ago=49, summary="")
    assert storage.list_meetings_pending_followup(min_age_hours=24) == []


def test_skips_meeting_when_already_sent(storage, cfg):
    _make_meeting(storage, hours_ago=49)
    storage.claim_followup("2026-04-28")
    assert storage.list_meetings_pending_followup(min_age_hours=24) == []


def test_skips_meeting_when_under_24h(storage, cfg):
    _make_meeting(storage, hours_ago=23)
    assert storage.list_meetings_pending_followup(min_age_hours=24) == []


def test_skips_meeting_after_7_day_cutoff(storage, cfg):
    _make_meeting(storage, hours_ago=24 * 8)
    assert storage.list_meetings_pending_followup(min_age_hours=24, max_age_days=7) == []


def test_pending_list_returns_due_meeting(storage, cfg):
    _make_meeting(storage, hours_ago=25)
    pending = storage.list_meetings_pending_followup(min_age_hours=24)
    assert len(pending) == 1
    assert pending[0]["id"] == "2026-04-28"


# claim_followup atomicity


def test_claim_is_idempotent(storage, cfg):
    _make_meeting(storage, hours_ago=25)
    assert storage.claim_followup("2026-04-28") is True
    assert storage.claim_followup("2026-04-28") is False


# end-to-end run() — happy path


def test_sends_meeting_when_due(storage, cfg):
    _make_meeting(storage, hours_ago=25, action_items=[
        {"id": "a1", "owner": "Bob Kennedy", "task": "Review the email"}
    ])
    gmail = FakeGmail()
    cal = _calendar_with(["rak@sixpeakcapital.com", "candresen@sixpeakcapital.com"])

    result = run(storage=storage, cfg=cfg, dry_run=False,
                 gmail_service=gmail, calendar_service=cal)

    assert result["sent"] == ["2026-04-28"]
    assert result["drafts"] == []
    assert len(gmail.sent) == 1
    sent = gmail.sent[0]
    assert "rak@sixpeakcapital.com" in sent["to"]
    assert "candresen@sixpeakcapital.com" in sent["to"]
    assert sent["from"] == "cma@sixpeakcapital.com"
    assert "L10 Follow-up — 2026-04-28" in sent["subject"]
    assert "Bob Kennedy" in sent["html"]
    # claim was set
    m = storage.get_meeting("2026-04-28")
    assert m["_followup_sent_at"] is not None
    assert m["_followup_log"]["dry_run"] is False
    assert m["_followup_log"]["recipients"] == ["rak@sixpeakcapital.com", "candresen@sixpeakcapital.com"]


def test_dry_run_creates_draft_only_to_sender(storage, cfg):
    _make_meeting(storage, hours_ago=25)
    gmail = FakeGmail()
    cal = _calendar_with(["rak@sixpeakcapital.com"])

    result = run(storage=storage, cfg=cfg, dry_run=True,
                 gmail_service=gmail, calendar_service=cal)

    assert result["sent"] == []
    assert result["drafts"] == ["2026-04-28"]
    assert len(gmail.created_drafts) == 1
    draft = gmail.created_drafts[0]
    assert draft["to"] == "cma@sixpeakcapital.com"  # only the sender
    assert draft["subject"].startswith("[DRY RUN]")
    # claim still set so we don't draft repeatedly
    m = storage.get_meeting("2026-04-28")
    assert m["_followup_sent_at"] is not None
    assert m["_followup_log"]["dry_run"] is True


def test_excludes_declined_invitees(storage, cfg):
    _make_meeting(storage, hours_ago=25)
    gmail = FakeGmail()
    cal = FakeCalendar(attendees=[
        {"email": "rak@sixpeakcapital.com", "responseStatus": "accepted"},
        {"email": "declined@sixpeakcapital.com", "responseStatus": "declined"},
    ])
    run(storage=storage, cfg=cfg, dry_run=False, gmail_service=gmail, calendar_service=cal)
    assert "declined@sixpeakcapital.com" not in gmail.sent[0]["to"]
    assert "rak@sixpeakcapital.com" in gmail.sent[0]["to"]


def test_excludes_resource_invitees(storage, cfg):
    _make_meeting(storage, hours_ago=25)
    gmail = FakeGmail()
    cal = FakeCalendar(attendees=[
        {"email": "rak@sixpeakcapital.com", "responseStatus": "accepted"},
        {"email": "boardroom@sixpeak.com", "responseStatus": "accepted", "resource": True},
    ])
    run(storage=storage, cfg=cfg, dry_run=False, gmail_service=gmail, calendar_service=cal)
    assert "boardroom" not in gmail.sent[0]["to"]


def test_excludes_sender_from_recipients(storage, cfg):
    _make_meeting(storage, hours_ago=25)
    gmail = FakeGmail()
    cal = _calendar_with(["cma@sixpeakcapital.com", "rak@sixpeakcapital.com"])
    run(storage=storage, cfg=cfg, dry_run=False, gmail_service=gmail, calendar_service=cal)
    # Sender should not be in To: line — only the other invitee
    assert gmail.sent[0]["to"] == "rak@sixpeakcapital.com"


def test_no_calendar_invitees_skips_without_claiming(storage, cfg):
    _make_meeting(storage, hours_ago=25)
    gmail = FakeGmail()
    cal = FakeCalendar(return_empty=True)
    result = run(storage=storage, cfg=cfg, dry_run=False,
                 gmail_service=gmail, calendar_service=cal)
    assert result["sent"] == []
    assert ("2026-04-28", "no calendar invitees") in result["skipped"]
    assert len(gmail.sent) == 0
    # claim NOT taken — retries next cycle
    m = storage.get_meeting("2026-04-28")
    assert m.get("_followup_sent_at") is None


def test_calendar_lookup_error_is_caught(storage, cfg):
    _make_meeting(storage, hours_ago=25)
    gmail = FakeGmail()
    cal = FakeCalendar(raise_error=RuntimeError("calendar API down"))
    result = run(storage=storage, cfg=cfg, dry_run=False,
                 gmail_service=gmail, calendar_service=cal)
    assert len(result["errors"]) == 1
    assert result["errors"][0][0] == "2026-04-28"
    assert "calendar API down" in result["errors"][0][1]
    # claim NOT taken — retries next cycle
    m = storage.get_meeting("2026-04-28")
    assert m.get("_followup_sent_at") is None


def test_send_failure_releases_claim(storage, cfg):
    _make_meeting(storage, hours_ago=25)
    gmail = FakeGmail()
    gmail.fail_on_send = True
    cal = _calendar_with(["rak@sixpeakcapital.com"])
    result = run(storage=storage, cfg=cfg, dry_run=False,
                 gmail_service=gmail, calendar_service=cal)
    assert len(result["errors"]) == 1
    # Claim was released so the next cron retries
    m = storage.get_meeting("2026-04-28")
    assert m.get("_followup_sent_at") is None
    # Error was logged
    assert "error" in (m.get("_followup_log") or {})


def test_lookup_invitees_picks_first_non_cancelled(cfg):
    cal = FakeCalendar()
    cal._return_instance = lambda: {"items": [
        {"status": "cancelled", "attendees": [{"email": "ghost@x.com"}]},
        {"status": "confirmed", "attendees": [{"email": "real@x.com"}]},
    ]}
    out = lookup_invitees(
        cal, calendar_id="primary", recurring_event_id="evt",
        meeting_date="2026-04-28", sender_email="cma@sixpeakcapital.com",
    )
    assert out == ["real@x.com"]


def test_lookup_invitees_dedupes(cfg):
    cal = FakeCalendar(attendees=[
        {"email": "a@x.com"},
        {"email": "A@X.com"},  # case-different duplicate
        {"email": "b@x.com"},
    ])
    out = lookup_invitees(
        cal, calendar_id="primary", recurring_event_id="evt",
        meeting_date="2026-04-28", sender_email="cma@sixpeakcapital.com",
    )
    assert len(out) == 2
    assert "a@x.com" in out
    assert "b@x.com" in out


def test_run_with_no_pending_meetings(storage, cfg):
    gmail = FakeGmail()
    cal = FakeCalendar()
    result = run(storage=storage, cfg=cfg, dry_run=False,
                 gmail_service=gmail, calendar_service=cal)
    assert result == {"checked": 0, "sent": [], "drafts": [], "skipped": [], "errors": []}


def test_html_contains_portal_link(storage, cfg):
    _make_meeting(storage, hours_ago=25)
    gmail = FakeGmail()
    cal = _calendar_with(["rak@sixpeakcapital.com"])
    run(storage=storage, cfg=cfg, dry_run=False, gmail_service=gmail, calendar_service=cal)
    sent = gmail.sent[0]
    assert "https://l10.sixpeakapps.com/meetings/2026-04-28" in sent["html"]
    assert "https://l10.sixpeakapps.com/meetings/2026-04-28" in sent["text"]


def test_open_todos_appear_in_email(storage, cfg):
    _make_meeting(storage, hours_ago=25)
    storage.add_todo({"owner": "Bob Kennedy", "task": "300 Deharo Resolution",
                      "due": "End of Jan 2026"})
    storage.add_todo({"owner": "Tom Taggart", "task": "Confirm submetering",
                      "due": "5/10/26"})
    gmail = FakeGmail()
    cal = _calendar_with(["rak@sixpeakcapital.com"])
    run(storage=storage, cfg=cfg, dry_run=False, gmail_service=gmail, calendar_service=cal)
    text = gmail.sent[0]["text"]
    assert "Bob Kennedy" in text
    assert "300 Deharo Resolution" in text
    assert "End of Jan 2026" in text
    assert "Tom Taggart" in text


def test_completed_todos_filtered(storage, cfg):
    _make_meeting(storage, hours_ago=25)
    storage.add_todo({"owner": "Bob", "task": "Open thing"})
    done = storage.add_todo({"owner": "Bob", "task": "Closed thing"})
    storage.toggle_todo(done["id"])  # mark complete
    gmail = FakeGmail()
    cal = _calendar_with(["rak@sixpeakcapital.com"])
    run(storage=storage, cfg=cfg, dry_run=False, gmail_service=gmail, calendar_service=cal)
    text = gmail.sent[0]["text"]
    assert "Open thing" in text
    assert "Closed thing" not in text
