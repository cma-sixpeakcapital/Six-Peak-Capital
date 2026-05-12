"""Tests for the Finance mid-cycle reminder email job.

Uses the file-backed Storage + inline fakes for Gmail and Calendar so
the suite is self-contained (no live OAuth, no real network).
"""
from __future__ import annotations

import base64
import email
import email.policy
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from app.config import Config
from app.jobs.reminder_template import render_email, estimated_next_call, render_subject
from app.jobs.send_reminders import run
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
        self.calls.append({"method": "instances", **kwargs})
        return _Exec(self._return_instance)

    def list(self, **kwargs):
        self.calls.append({"method": "list", **kwargs})
        return _Exec(lambda: {"items": []})

    def _return_instance(self) -> dict[str, Any]:
        if self.raise_error:
            raise self.raise_error
        if self.return_empty:
            return {"items": []}
        return {"items": [{"status": "confirmed", "attendees": self.attendees}]}


def _calendar_with(emails: list[str]) -> FakeCalendar:
    return FakeCalendar(attendees=[{"email": e, "responseStatus": "accepted"} for e in emails])


# --- Fixtures --------------------------------------------------------------


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
        followup_portal_name="Six Peak Monthly Finance",
        followup_portal_url="https://finance.sixpeakapps.com",
        followup_reminder_subject_prefix="Finance Check-in",
        followup_reminder_min_age_days=14,
        followup_reminder_max_age_days=21,
    )


def _make_meeting(storage: Storage, *, days_ago: int, summary: str = "Recap. Bullet two.",
                  meeting_id: str = "fin_2026_04_28") -> dict[str, Any]:
    meeting_date = (date.today() - timedelta(days=days_ago)).isoformat()
    storage.save_meeting({
        "id": meeting_id,
        "date": meeting_date,
        "title": "Six Peak Monthly Finance call",
        "summary": summary,
        "action_items": [],
        "saved_at": datetime.now(timezone.utc).isoformat(),
    })
    return storage.get_meeting(meeting_id) or {}


def _add_open_todo(storage: Storage, owner: str, task: str, due: str = "") -> dict[str, Any]:
    return storage.add_todo({"owner": owner, "task": task, "due": due})


def _add_open_goal(storage: Storage, title: str, due: str = "") -> dict[str, Any]:
    return storage.add_goal({"title": title, "due": due})


# --- Template tests --------------------------------------------------------


def test_estimated_next_call_handles_monthly_rollover():
    assert estimated_next_call("2026-04-28") == "May 28"
    assert estimated_next_call("2026-01-31") == "February 28"
    assert estimated_next_call("not-a-date") == "in ~4 weeks"


def test_subject_is_forward_looking(cfg):
    meeting = {"id": "x", "date": "2026-04-28", "title": "Finance"}
    assert render_subject(cfg.followup_reminder_subject_prefix, meeting) == \
        "Finance Check-in — open items 2 weeks before next call"


def test_template_is_clearly_automated(cfg):
    meeting = {"id": "x", "date": "2026-04-28", "summary": "Recap."}
    todos = [{"owner": "Bob", "task": "Do thing"}]
    _, html, text = render_email(
        meeting, todos, [],
        subject_prefix="Finance Check-in",
        portal_name="Six Peak Monthly Finance",
        portal_url="https://finance.sixpeakapps.com",
    )
    # Header makes clear it's automated
    assert "Automated reminder" in text
    assert "Automated reminder" in html
    # Footer disclaims automation, says don't reply
    assert "sent automatically" in text
    assert "sent automatically" in html
    assert "Do not reply" in text or "do not reply" in text.lower()
    # No personal sign-off, no "reply here" instruction
    assert "— Chris" not in text
    assert "— Chris" not in html
    assert "reply here" not in text.lower()


def test_template_includes_next_call_date(cfg):
    meeting = {"id": "x", "date": "2026-04-28", "summary": "Recap."}
    _, html, text = render_email(
        meeting, [{"owner": "Bob", "task": "Thing"}], [],
        subject_prefix="Finance Check-in",
        portal_name="Six Peak Monthly Finance",
        portal_url="https://finance.sixpeakapps.com",
    )
    assert "May 28" in text
    assert "May 28" in html


def test_template_includes_portal_name(cfg):
    meeting = {"id": "x", "date": "2026-04-28", "summary": "Recap."}
    _, html, text = render_email(
        meeting, [{"owner": "Bob", "task": "Thing"}], [],
        subject_prefix="Finance Check-in",
        portal_name="Six Peak Monthly Finance",
        portal_url="https://finance.sixpeakapps.com",
    )
    assert "Six Peak Monthly Finance" in text
    assert "Six Peak Monthly Finance" in html


def test_template_groups_todos_by_owner(cfg):
    meeting = {"id": "x", "date": "2026-04-28", "summary": "Recap."}
    todos = [
        {"owner": "Bob", "task": "B1"},
        {"owner": "Alice", "task": "A1"},
        {"owner": "Bob", "task": "B2"},
    ]
    _, _, text = render_email(
        meeting, todos, [],
        subject_prefix="Finance Check-in",
        portal_name="Six Peak Monthly Finance",
        portal_url="https://finance.sixpeakapps.com",
    )
    assert text.index("Alice") < text.index("Bob")
    assert text.count("Bob") == 1
    assert "B1" in text and "B2" in text


def test_template_renders_goals_section(cfg):
    meeting = {"id": "x", "date": "2026-04-28", "summary": "Recap."}
    goals = [
        {"title": "Yardi migration end-to-end", "due": "Q2 2026", "status": "incomplete"},
        {"title": "Quarterly variance reporting", "due": "", "status": "incomplete"},
    ]
    _, html, text = render_email(
        meeting, [], goals,
        subject_prefix="Finance Check-in",
        portal_name="Six Peak Monthly Finance",
        portal_url="https://finance.sixpeakapps.com",
    )
    assert "OPEN GOALS" in text
    assert "Yardi migration end-to-end" in text
    assert "Q2 2026" in text
    assert "Quarterly variance reporting" in text


def test_template_shows_none_open_when_empty(cfg):
    """When one section is empty, render '(none open)' rather than dropping
    the section entirely. The send_reminders.run() skip-silent rule kicks
    in only when BOTH are empty."""
    meeting = {"id": "x", "date": "2026-04-28", "summary": "Recap."}
    todos = [{"owner": "Bob", "task": "Thing"}]
    _, _, text = render_email(
        meeting, todos, [],
        subject_prefix="Finance Check-in",
        portal_name="Six Peak Monthly Finance",
        portal_url="https://finance.sixpeakapps.com",
    )
    # Todos section has Bob's task, goals section says (none open)
    assert "OPEN TO-DOS" in text
    assert "Bob" in text
    assert "OPEN GOALS" in text
    assert "(none open)" in text


# --- Pending-list filter tests --------------------------------------------


def test_skips_meeting_under_14_days(storage, cfg):
    _make_meeting(storage, days_ago=13)
    assert storage.list_meetings_pending_reminder(min_age_days=14, max_age_days=21) == []


def test_skips_meeting_over_21_days(storage, cfg):
    _make_meeting(storage, days_ago=22)
    assert storage.list_meetings_pending_reminder(min_age_days=14, max_age_days=21) == []


def test_pending_list_returns_due_meeting(storage, cfg):
    _make_meeting(storage, days_ago=14)
    pending = storage.list_meetings_pending_reminder(min_age_days=14, max_age_days=21)
    assert len(pending) == 1
    assert pending[0]["id"] == "fin_2026_04_28"


def test_skips_meeting_with_blank_summary(storage, cfg):
    _make_meeting(storage, days_ago=14, summary="")
    assert storage.list_meetings_pending_reminder(min_age_days=14, max_age_days=21) == []


def test_skips_meeting_when_already_sent(storage, cfg):
    _make_meeting(storage, days_ago=14)
    storage.claim_reminder("fin_2026_04_28")
    assert storage.list_meetings_pending_reminder(min_age_days=14, max_age_days=21) == []


# --- claim atomicity -------------------------------------------------------


def test_claim_is_idempotent(storage, cfg):
    _make_meeting(storage, days_ago=14)
    assert storage.claim_reminder("fin_2026_04_28") is True
    assert storage.claim_reminder("fin_2026_04_28") is False


# --- end-to-end run() ------------------------------------------------------


def test_skip_silently_when_no_open_todos_or_goals(storage, cfg):
    """Both empty → skip without claiming."""
    _make_meeting(storage, days_ago=14)
    # No todos, no goals added
    gmail = FakeGmail()
    cal = _calendar_with(["candresen@sixpeakcapital.com"])
    result = run(storage=storage, cfg=cfg, dry_run=False,
                 gmail_service=gmail, calendar_service=cal)
    assert result["sent"] == []
    assert result["drafts"] == []
    assert ("fin_2026_04_28", "no open to-dos or goals") in result["skipped"]
    assert len(gmail.sent) == 0
    m = storage.get_meeting("fin_2026_04_28")
    assert m.get("_reminder_sent_at") is None


def test_fires_when_only_todos_have_content(storage, cfg):
    """Todos present, goals empty → still send (goals section shows '(none open)')."""
    _make_meeting(storage, days_ago=14)
    _add_open_todo(storage, "Bob", "Thing")
    gmail = FakeGmail()
    cal = _calendar_with(["rak@sixpeakcapital.com"])
    result = run(storage=storage, cfg=cfg, dry_run=False,
                 gmail_service=gmail, calendar_service=cal)
    assert result["sent"] == ["fin_2026_04_28"]
    sent = gmail.sent[0]
    assert "OPEN TO-DOS" in sent["text"]
    assert "OPEN GOALS" in sent["text"]
    # Goals section says "(none open)"
    goals_idx = sent["text"].index("OPEN GOALS")
    assert "(none open)" in sent["text"][goals_idx:]


def test_fires_when_only_goals_have_content(storage, cfg):
    """Goals present, todos empty → still send."""
    _make_meeting(storage, days_ago=14)
    _add_open_goal(storage, "Migrate Yardi")
    gmail = FakeGmail()
    cal = _calendar_with(["rak@sixpeakcapital.com"])
    result = run(storage=storage, cfg=cfg, dry_run=False,
                 gmail_service=gmail, calendar_service=cal)
    assert result["sent"] == ["fin_2026_04_28"]
    sent = gmail.sent[0]
    assert "Migrate Yardi" in sent["text"]


def test_sends_reminder_with_both_todos_and_goals(storage, cfg):
    _make_meeting(storage, days_ago=14)
    _add_open_todo(storage, "Chris Andresen", "Send Grady the historical payroll data")
    _add_open_todo(storage, "Grady Lakamp", "Provide pre-construction invoices", due="5/15")
    _add_open_goal(storage, "Yardi migration end-to-end", due="Q2 2026")
    gmail = FakeGmail()
    cal = _calendar_with(["candresen@sixpeakcapital.com", "grady@lvllc.com"])

    result = run(storage=storage, cfg=cfg, dry_run=False,
                 gmail_service=gmail, calendar_service=cal)

    assert result["sent"] == ["fin_2026_04_28"]
    assert len(gmail.sent) == 1
    sent = gmail.sent[0]
    assert "candresen@sixpeakcapital.com" in sent["to"]
    assert "grady@lvllc.com" in sent["to"]
    assert "Finance Check-in" in sent["subject"]
    assert "Send Grady the historical payroll data" in sent["html"]
    assert "Provide pre-construction invoices" in sent["html"]
    assert "5/15" in sent["html"]
    assert "Yardi migration end-to-end" in sent["html"]
    assert "Q2 2026" in sent["html"]
    # claim was set, log captures both counts
    m = storage.get_meeting("fin_2026_04_28")
    assert m["_reminder_sent_at"] is not None
    assert m["_reminder_log"]["dry_run"] is False
    assert m["_reminder_log"]["open_todos_count"] == 2
    assert m["_reminder_log"]["open_goals_count"] == 1


def test_completed_goals_filtered_out(storage, cfg):
    _make_meeting(storage, days_ago=14)
    _add_open_goal(storage, "Open goal")
    done = _add_open_goal(storage, "Closed goal")
    storage.toggle_goal(done["id"])  # mark complete
    gmail = FakeGmail()
    cal = _calendar_with(["rak@sixpeakcapital.com"])
    run(storage=storage, cfg=cfg, dry_run=False,
        gmail_service=gmail, calendar_service=cal)
    sent = gmail.sent[0]
    assert "Open goal" in sent["text"]
    assert "Closed goal" not in sent["text"]


def test_dry_run_creates_draft_only_to_sender(storage, cfg):
    _make_meeting(storage, days_ago=14)
    _add_open_todo(storage, "Bob", "Do a thing")
    gmail = FakeGmail()
    cal = _calendar_with(["rak@sixpeakcapital.com"])

    result = run(storage=storage, cfg=cfg, dry_run=True,
                 gmail_service=gmail, calendar_service=cal)

    assert result["sent"] == []
    assert result["drafts"] == ["fin_2026_04_28"]
    assert len(gmail.created_drafts) == 1
    draft = gmail.created_drafts[0]
    assert draft["to"] == "cma@sixpeakcapital.com"
    assert draft["subject"].startswith("[DRY RUN]")


def test_completed_todos_are_filtered_before_send(storage, cfg):
    _make_meeting(storage, days_ago=14)
    _add_open_todo(storage, "Bob", "Open task")
    done = _add_open_todo(storage, "Bob", "Closed task")
    storage.toggle_todo(done["id"])
    gmail = FakeGmail()
    cal = _calendar_with(["rak@sixpeakcapital.com"])

    run(storage=storage, cfg=cfg, dry_run=False,
        gmail_service=gmail, calendar_service=cal)

    sent = gmail.sent[0]
    assert "Open task" in sent["text"]
    assert "Closed task" not in sent["text"]


def test_no_calendar_invitees_skips_without_claiming(storage, cfg):
    _make_meeting(storage, days_ago=14)
    _add_open_todo(storage, "Bob", "Do thing")
    gmail = FakeGmail()
    cal = FakeCalendar(return_empty=True)

    result = run(storage=storage, cfg=cfg, dry_run=False,
                 gmail_service=gmail, calendar_service=cal)

    assert result["sent"] == []
    assert ("fin_2026_04_28", "no calendar invitees") in result["skipped"]
    m = storage.get_meeting("fin_2026_04_28")
    assert m.get("_reminder_sent_at") is None


def test_calendar_lookup_error_caught(storage, cfg):
    _make_meeting(storage, days_ago=14)
    _add_open_todo(storage, "Bob", "Do thing")
    gmail = FakeGmail()
    cal = FakeCalendar(raise_error=RuntimeError("calendar API down"))

    result = run(storage=storage, cfg=cfg, dry_run=False,
                 gmail_service=gmail, calendar_service=cal)

    assert len(result["errors"]) == 1
    m = storage.get_meeting("fin_2026_04_28")
    assert m.get("_reminder_sent_at") is None


def test_send_failure_releases_claim(storage, cfg):
    _make_meeting(storage, days_ago=14)
    _add_open_todo(storage, "Bob", "Do thing")
    gmail = FakeGmail()
    gmail.fail_on_send = True
    cal = _calendar_with(["rak@sixpeakcapital.com"])

    result = run(storage=storage, cfg=cfg, dry_run=False,
                 gmail_service=gmail, calendar_service=cal)

    assert len(result["errors"]) == 1
    m = storage.get_meeting("fin_2026_04_28")
    assert m.get("_reminder_sent_at") is None
    assert "error" in (m.get("_reminder_log") or {})


def test_excludes_declined_invitees(storage, cfg):
    _make_meeting(storage, days_ago=14)
    _add_open_todo(storage, "Bob", "Do thing")
    gmail = FakeGmail()
    cal = FakeCalendar(attendees=[
        {"email": "rak@sixpeakcapital.com", "responseStatus": "accepted"},
        {"email": "declined@sixpeakcapital.com", "responseStatus": "declined"},
    ])
    run(storage=storage, cfg=cfg, dry_run=False, gmail_service=gmail, calendar_service=cal)
    assert "declined@sixpeakcapital.com" not in gmail.sent[0]["to"]


def test_excludes_sender_from_recipients(storage, cfg):
    _make_meeting(storage, days_ago=14)
    _add_open_todo(storage, "Bob", "Do thing")
    gmail = FakeGmail()
    cal = _calendar_with(["cma@sixpeakcapital.com", "rak@sixpeakcapital.com"])
    run(storage=storage, cfg=cfg, dry_run=False, gmail_service=gmail, calendar_service=cal)
    assert gmail.sent[0]["to"] == "rak@sixpeakcapital.com"


def test_link_points_to_main_portal_not_meeting_page(storage, cfg):
    """Reminder links to the portal root (to-do list view), not the specific
    meeting page — the reminder is forward-looking."""
    _make_meeting(storage, days_ago=14)
    _add_open_todo(storage, "Bob", "Do thing")
    gmail = FakeGmail()
    cal = _calendar_with(["rak@sixpeakcapital.com"])
    run(storage=storage, cfg=cfg, dry_run=False, gmail_service=gmail, calendar_service=cal)
    sent = gmail.sent[0]
    assert "https://finance.sixpeakapps.com" in sent["html"]
    assert "https://finance.sixpeakapps.com" in sent["text"]
    assert "/meetings/" not in sent["html"]
    assert "/meetings/" not in sent["text"]
    assert "Update your status in the portal" in sent["text"]


def test_run_with_no_pending_meetings(storage, cfg):
    gmail = FakeGmail()
    cal = FakeCalendar()
    result = run(storage=storage, cfg=cfg, dry_run=False,
                 gmail_service=gmail, calendar_service=cal)
    assert result == {"checked": 0, "sent": [], "drafts": [], "skipped": [], "errors": []}


def test_first_reminder_on_day_14_exactly(storage, cfg):
    """Tomorrow's launch case: meeting on day-14 boundary should fire."""
    _make_meeting(storage, days_ago=14)
    _add_open_todo(storage, "Chris Aiello", "Tomorrow's first reminder")
    gmail = FakeGmail()
    cal = _calendar_with(["candresen@sixpeakcapital.com"])
    result = run(storage=storage, cfg=cfg, dry_run=True,
                 gmail_service=gmail, calendar_service=cal)
    assert result["drafts"] == ["fin_2026_04_28"]
    assert len(gmail.created_drafts) == 1
