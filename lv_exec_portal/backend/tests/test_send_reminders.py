"""Tests for the LV Exec mid-cycle reminder email job."""
from __future__ import annotations

import base64
import email
import email.policy
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from app.config import Config
from app.jobs.reminder_template import (
    estimated_next_call,
    render_email,
    render_subject,
)
from app.jobs.send_reminders import run
from app.storage import Storage


# --- Fakes ---------------------------------------------------------------


class FakeGmail:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.created_drafts: list[dict[str, Any]] = []
        self.fail_on_send = False

    def users(self): return self
    def messages(self): return self
    def drafts(self): return _DraftsHandle(self)

    def send(self, *, userId, body):
        return _Exec(self._do_send, body)

    def _do_send(self, body):
        if self.fail_on_send:
            raise RuntimeError("simulated Gmail outage")
        self.sent.append(_decode_raw(body["raw"]))
        return {"id": f"msg_{len(self.sent)}"}


class _DraftsHandle:
    def __init__(self, parent): self.parent = parent
    def create(self, *, userId, body): return _Exec(self._do_create, body)
    def _do_create(self, body):
        self.parent.created_drafts.append(_decode_raw(body["message"]["raw"]))
        return {"id": f"draft_{len(self.parent.created_drafts)}"}


class _Exec:
    def __init__(self, fn, *args): self.fn = fn; self.args = args
    def execute(self): return self.fn(*self.args)


def _decode_raw(raw_b64):
    raw_bytes = base64.urlsafe_b64decode(raw_b64.encode("ascii"))
    msg = email.message_from_bytes(raw_bytes, policy=email.policy.default)
    parts = {}
    for part in msg.walk():
        ctype = part.get_content_type()
        if ctype in ("text/plain", "text/html"):
            c = part.get_content()
            if isinstance(c, bytes): c = c.decode("utf-8", errors="replace")
            parts[ctype] = c
    return {
        "from": str(msg["From"] or ""),
        "to": str(msg["To"] or ""),
        "cc": str(msg["Cc"] or ""),
        "subject": str(msg["Subject"] or ""),
        "text": parts.get("text/plain", ""),
        "html": parts.get("text/html", ""),
    }


class FakeCalendar:
    def __init__(self, attendees=None, raise_error=None, return_empty=False):
        self.attendees = attendees or []
        self.raise_error = raise_error
        self.return_empty = return_empty

    def events(self): return self
    def instances(self, **kw): return _Exec(self._return_instance)
    def list(self, **kw): return _Exec(lambda: {"items": []})

    def _return_instance(self):
        if self.raise_error: raise self.raise_error
        if self.return_empty: return {"items": []}
        return {"items": [{"status": "confirmed", "attendees": self.attendees}]}


def _calendar_with(emails):
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
        followup_portal_name="LV Executive",
        followup_portal_url="https://lvexec.sixpeakapps.com",
        followup_reminder_subject_prefix="LV Exec Check-in",
        followup_reminder_min_age_days=7,
        followup_reminder_max_age_days=14,
    )


def _make_meeting(storage, *, days_ago, summary="Recap.", meeting_id="lv_test"):
    meeting_date = (date.today() - timedelta(days=days_ago)).isoformat()
    storage.save_meeting({
        "id": meeting_id,
        "date": meeting_date,
        "title": "LV Executive meeting - bi-weekly",
        "summary": summary,
        "action_items": [],
        "saved_at": datetime.now(timezone.utc).isoformat(),
    })
    return storage.get_meeting(meeting_id) or {}


def _add_open_todo(storage, owner, task, due=""):
    return storage.add_todo({"owner": owner, "task": task, "due": due})


def _add_open_goal(storage, title, due=""):
    return storage.add_goal({"title": title, "due": due})


# --- Template tests --------------------------------------------------------


def test_estimated_next_call_biweekly():
    assert estimated_next_call("2026-04-28") == "May 12"
    assert estimated_next_call("not-a-date") == "in ~2 weeks"


def test_subject_is_forward_looking(cfg):
    meeting = {"id": "x", "date": "2026-04-28", "title": "LV Exec"}
    assert render_subject(cfg.followup_reminder_subject_prefix, meeting) == \
        "LV Exec Check-in — open items before next call"


def test_template_is_clearly_automated(cfg):
    meeting = {"id": "x", "date": "2026-04-28", "summary": "Recap."}
    todos = [{"owner": "Bob", "task": "Do thing"}]
    _, html, text = render_email(
        meeting, todos, [],
        subject_prefix="LV Exec Check-in",
        portal_name="LV Executive",
        portal_url="https://lvexec.sixpeakapps.com",
    )
    assert "Automated reminder" in text
    assert "sent automatically" in text
    assert "— Chris" not in text


def test_template_renders_goals_section(cfg):
    meeting = {"id": "x", "date": "2026-04-28", "summary": "Recap."}
    goals = [
        {"title": "Goal 1", "due": "Q2", "status": "incomplete"},
        {"title": "Goal 2", "due": "", "status": "incomplete"},
    ]
    _, _, text = render_email(
        meeting, [], goals,
        subject_prefix="LV Exec Check-in",
        portal_name="LV Executive",
        portal_url="https://lvexec.sixpeakapps.com",
    )
    assert "OPEN GOALS" in text
    assert "Goal 1" in text
    assert "Q2" in text
    assert "Goal 2" in text


# --- Pending-list filter tests --------------------------------------------


def test_skips_meeting_under_7_days(storage, cfg):
    _make_meeting(storage, days_ago=6)
    assert storage.list_meetings_pending_reminder(min_age_days=7, max_age_days=14) == []


def test_skips_meeting_over_14_days(storage, cfg):
    _make_meeting(storage, days_ago=15)
    assert storage.list_meetings_pending_reminder(min_age_days=7, max_age_days=14) == []


def test_pending_list_returns_due_meeting(storage, cfg):
    _make_meeting(storage, days_ago=7)
    pending = storage.list_meetings_pending_reminder(min_age_days=7, max_age_days=14)
    assert len(pending) == 1


def test_claim_is_idempotent(storage, cfg):
    _make_meeting(storage, days_ago=7)
    assert storage.claim_reminder("lv_test") is True
    assert storage.claim_reminder("lv_test") is False


# --- End-to-end ----------------------------------------------------------


def test_skip_silently_when_no_open_items(storage, cfg):
    _make_meeting(storage, days_ago=7)
    gmail = FakeGmail()
    cal = _calendar_with(["rak@sixpeakcapital.com"])
    result = run(storage=storage, cfg=cfg, dry_run=False,
                 gmail_service=gmail, calendar_service=cal)
    assert ("lv_test", "no open to-dos or goals") in result["skipped"]


def test_fires_when_only_todos_have_content(storage, cfg):
    _make_meeting(storage, days_ago=7)
    _add_open_todo(storage, "Bob", "Thing")
    gmail = FakeGmail()
    cal = _calendar_with(["rak@sixpeakcapital.com"])
    result = run(storage=storage, cfg=cfg, dry_run=False,
                 gmail_service=gmail, calendar_service=cal)
    assert result["sent"] == ["lv_test"]


def test_fires_when_only_goals_have_content(storage, cfg):
    _make_meeting(storage, days_ago=7)
    _add_open_goal(storage, "Build the thing")
    gmail = FakeGmail()
    cal = _calendar_with(["rak@sixpeakcapital.com"])
    result = run(storage=storage, cfg=cfg, dry_run=False,
                 gmail_service=gmail, calendar_service=cal)
    assert result["sent"] == ["lv_test"]
    assert "Build the thing" in gmail.sent[0]["text"]


def test_sends_with_both_todos_and_goals(storage, cfg):
    _make_meeting(storage, days_ago=7)
    _add_open_todo(storage, "Grady Lakamp", "Coordinate with Pedro")
    _add_open_goal(storage, "Q2 hiring plan", due="June")
    gmail = FakeGmail()
    cal = _calendar_with(["candresen@sixpeakcapital.com"])
    result = run(storage=storage, cfg=cfg, dry_run=False,
                 gmail_service=gmail, calendar_service=cal)
    assert result["sent"] == ["lv_test"]
    sent = gmail.sent[0]
    assert "LV Exec Check-in" in sent["subject"]
    assert "Grady Lakamp" in sent["html"]
    assert "Coordinate with Pedro" in sent["html"]
    assert "Q2 hiring plan" in sent["html"]
    assert "June" in sent["html"]


def test_completed_goals_filtered_out(storage, cfg):
    _make_meeting(storage, days_ago=7)
    _add_open_goal(storage, "Open goal")
    done = _add_open_goal(storage, "Closed goal")
    storage.toggle_goal(done["id"])
    gmail = FakeGmail()
    cal = _calendar_with(["rak@sixpeakcapital.com"])
    run(storage=storage, cfg=cfg, dry_run=False, gmail_service=gmail, calendar_service=cal)
    sent = gmail.sent[0]
    assert "Open goal" in sent["text"]
    assert "Closed goal" not in sent["text"]


def test_dry_run_creates_draft_only_to_sender(storage, cfg):
    _make_meeting(storage, days_ago=7)
    _add_open_todo(storage, "Bob", "Thing")
    gmail = FakeGmail()
    cal = _calendar_with(["rak@sixpeakcapital.com"])
    result = run(storage=storage, cfg=cfg, dry_run=True,
                 gmail_service=gmail, calendar_service=cal)
    assert result["drafts"] == ["lv_test"]
    draft = gmail.created_drafts[0]
    assert draft["to"] == "cma@sixpeakcapital.com"
    assert draft["subject"].startswith("[DRY RUN]")
    # Non-consuming: no claim, no sent_at, no log — repeatable.
    m = storage.get_meeting("lv_test")
    assert m.get("_reminder_sent_at") is None
    assert m.get("_reminder_log") is None
    still_pending = storage.list_meetings_pending_reminder(min_age_days=7, max_age_days=14)
    assert any(x["id"] == "lv_test" for x in still_pending)


def test_preview_does_not_consume(storage, cfg):
    _make_meeting(storage, days_ago=7)
    _add_open_todo(storage, "Bob", "Thing")
    gmail = FakeGmail()
    cal = _calendar_with(["rak@sixpeakcapital.com"])
    result = run(storage=storage, cfg=cfg, dry_run=False, preview=True,
                 gmail_service=gmail, calendar_service=cal)
    assert result["sent"] == [] and result["drafts"] == []
    assert [w["meeting_id"] for w in result["would_send"]] == ["lv_test"]
    assert result["would_send"][0]["recipients"] == ["rak@sixpeakcapital.com"]
    assert gmail.sent == [] and gmail.created_drafts == []
    m = storage.get_meeting("lv_test")
    assert m.get("_reminder_sent_at") is None
    assert m.get("_reminder_log") is None


def test_preview_include_claimed_surfaces_blocked(storage, cfg):
    _make_meeting(storage, days_ago=7)
    _add_open_todo(storage, "Bob", "Thing")
    storage.claim_reminder("lv_test")
    cal = _calendar_with(["rak@sixpeakcapital.com"])
    default_preview = run(storage=storage, cfg=cfg, dry_run=False, preview=True,
                          gmail_service=FakeGmail(), calendar_service=cal)
    assert default_preview["would_send"] == []
    inclusive = run(storage=storage, cfg=cfg, dry_run=False, preview=True,
                    include_claimed=True, gmail_service=FakeGmail(), calendar_service=cal)
    assert [w["meeting_id"] for w in inclusive["would_send"]] == ["lv_test"]
    m = storage.get_meeting("lv_test")
    assert m.get("_reminder_sent_at") is not None  # still claimed, untouched


def test_link_points_to_main_portal(storage, cfg):
    _make_meeting(storage, days_ago=7)
    _add_open_todo(storage, "Bob", "Thing")
    gmail = FakeGmail()
    cal = _calendar_with(["rak@sixpeakcapital.com"])
    run(storage=storage, cfg=cfg, dry_run=False, gmail_service=gmail, calendar_service=cal)
    sent = gmail.sent[0]
    assert "https://lvexec.sixpeakapps.com" in sent["text"]
    assert "/meetings/" not in sent["text"]


def test_excludes_sender_from_recipients(storage, cfg):
    _make_meeting(storage, days_ago=7)
    _add_open_todo(storage, "Bob", "Thing")
    gmail = FakeGmail()
    cal = _calendar_with(["cma@sixpeakcapital.com", "rak@sixpeakcapital.com"])
    run(storage=storage, cfg=cfg, dry_run=False, gmail_service=gmail, calendar_service=cal)
    assert gmail.sent[0]["to"] == "rak@sixpeakcapital.com"


def test_real_send_ccs_the_sender(storage, cfg):
    """Real sends CC the sender so Chris gets a copy in his inbox."""
    _make_meeting(storage, days_ago=7)
    _add_open_todo(storage, "Bob", "Thing")
    gmail = FakeGmail()
    cal = _calendar_with(["rak@sixpeakcapital.com"])
    run(storage=storage, cfg=cfg, dry_run=False, gmail_service=gmail, calendar_service=cal)
    assert gmail.sent[0]["cc"] == "cma@sixpeakcapital.com"


def test_dry_run_draft_has_no_cc(storage, cfg):
    """Drafts (dry-run) are addressed only to sender — no CC needed."""
    _make_meeting(storage, days_ago=7)
    _add_open_todo(storage, "Bob", "Thing")
    gmail = FakeGmail()
    cal = _calendar_with(["rak@sixpeakcapital.com"])
    run(storage=storage, cfg=cfg, dry_run=True, gmail_service=gmail, calendar_service=cal)
    assert gmail.created_drafts[0]["cc"] == ""


def test_no_calendar_invitees_skips_without_claiming(storage, cfg):
    _make_meeting(storage, days_ago=7)
    _add_open_todo(storage, "Bob", "Thing")
    gmail = FakeGmail()
    cal = FakeCalendar(return_empty=True)
    result = run(storage=storage, cfg=cfg, dry_run=False,
                 gmail_service=gmail, calendar_service=cal)
    assert ("lv_test", "no calendar invitees") in result["skipped"]
    m = storage.get_meeting("lv_test")
    assert m.get("_reminder_sent_at") is None


def test_send_failure_releases_claim(storage, cfg):
    _make_meeting(storage, days_ago=7)
    _add_open_todo(storage, "Bob", "Thing")
    gmail = FakeGmail()
    gmail.fail_on_send = True
    cal = _calendar_with(["rak@sixpeakcapital.com"])
    result = run(storage=storage, cfg=cfg, dry_run=False,
                 gmail_service=gmail, calendar_service=cal)
    assert len(result["errors"]) == 1
    m = storage.get_meeting("lv_test")
    assert m.get("_reminder_sent_at") is None


def test_run_with_no_pending_meetings(storage, cfg):
    gmail = FakeGmail()
    cal = FakeCalendar()
    result = run(storage=storage, cfg=cfg, dry_run=False,
                 gmail_service=gmail, calendar_service=cal)
    assert result == {"checked": 0, "sent": [], "drafts": [], "skipped": [], "errors": [], "would_send": []}
