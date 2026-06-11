"""Tests for the L10 mid-cycle reminder email job.

Uses the file-backed Storage + inline fakes for Gmail and Calendar.
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
from app.jobs.reminder_template import (
    estimated_next_call,
    open_rocks_by_owner,
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
        followup_portal_name="L10 Weekly",
        followup_portal_url="https://l10.sixpeakapps.com",
        followup_reminder_subject_prefix="L10 Check-in",
        followup_reminder_min_age_days=3,
        followup_reminder_max_age_days=10,
    )


def _make_meeting(storage, *, days_ago, summary="Recap.", meeting_id="l10_test",
                  kind="l10", title="Six Peak Capital - Weekly L10"):
    meeting_date = (date.today() - timedelta(days=days_ago)).isoformat()
    storage.save_meeting({
        "id": meeting_id,
        "date": meeting_date,
        "title": title,
        "kind": kind,
        "summary": summary,
        "action_items": [],
        "saved_at": datetime.now(timezone.utc).isoformat(),
    })
    return storage.get_meeting(meeting_id) or {}


def _add_open_todo(storage, owner, task, due=""):
    return storage.add_todo({"owner": owner, "task": task, "due": due})


def _add_open_rock(storage, owner, title, category="", due=""):
    return storage.add_person_rock(owner, {"title": title, "category": category, "due": due})


# --- Template tests --------------------------------------------------------


def test_estimated_next_call_weekly():
    assert estimated_next_call("2026-04-28") == "May 5"
    assert estimated_next_call("not-a-date") == "in ~1 week"


def test_subject_is_forward_looking(cfg):
    meeting = {"id": "x", "date": "2026-04-28", "title": "L10"}
    assert render_subject(cfg.followup_reminder_subject_prefix, meeting) == \
        "L10 Check-in — open items before next call"


def test_template_is_clearly_automated(cfg):
    meeting = {"id": "x", "date": "2026-04-28", "summary": "Recap."}
    todos = [{"owner": "Bob", "task": "Do thing"}]
    _, html, text = render_email(
        meeting, todos, [],
        subject_prefix="L10 Check-in",
        portal_name="L10 Weekly",
        portal_url="https://l10.sixpeakapps.com",
    )
    assert "Automated reminder" in text
    assert "sent automatically" in text
    assert "— Chris" not in text
    assert "reply here" not in text.lower()


def test_template_includes_next_call_date(cfg):
    meeting = {"id": "x", "date": "2026-04-28", "summary": "Recap."}
    _, _, text = render_email(
        meeting, [{"owner": "Bob", "task": "Thing"}], [],
        subject_prefix="L10 Check-in",
        portal_name="L10 Weekly",
        portal_url="https://l10.sixpeakapps.com",
    )
    # April 28 + 7d = May 5
    assert "May 5" in text


def test_open_rocks_by_owner_filters_complete():
    rocks_doc = {
        "rocks": {
            "Bob": [
                {"title": "Open 1", "status": "incomplete"},
                {"title": "Done", "status": "complete"},
            ],
            "Alice": [{"title": "Open 2", "status": "incomplete"}],
        },
        "company_rocks": [
            {"title": "Co open", "status": "incomplete"},
            {"title": "Co done", "status": "complete"},
        ],
    }
    out = open_rocks_by_owner(rocks_doc)
    owners = [o for o, _ in out]
    # Alphabetical personal owners, then Company-wide
    assert owners == ["Alice", "Bob", "Company-wide"]
    bob = next(rocks for o, rocks in out if o == "Bob")
    assert len(bob) == 1
    assert bob[0]["title"] == "Open 1"
    co = next(rocks for o, rocks in out if o == "Company-wide")
    assert len(co) == 1
    assert co[0]["title"] == "Co open"


def test_open_rocks_by_owner_skips_owners_with_zero_open():
    rocks_doc = {
        "rocks": {
            "Bob": [{"title": "Done", "status": "complete"}],
            "Alice": [{"title": "Open", "status": "incomplete"}],
        },
        "company_rocks": [],
    }
    out = open_rocks_by_owner(rocks_doc)
    owners = [o for o, _ in out]
    assert owners == ["Alice"]
    # No 'Company-wide' since list is empty


def test_template_renders_rocks_section(cfg):
    meeting = {"id": "x", "date": "2026-04-28", "summary": "Recap."}
    rocks_by_owner = [
        ("Bob Kennedy", [{"title": "MRK Negotiations", "due": "Q2 2026", "status": "incomplete"}]),
        ("Company-wide", [{"title": "Annual planning", "due": ""}]),
    ]
    _, html, text = render_email(
        meeting, [], rocks_by_owner,
        subject_prefix="L10 Check-in",
        portal_name="L10 Weekly",
        portal_url="https://l10.sixpeakapps.com",
    )
    assert "OPEN ROCKS" in text
    assert "Bob Kennedy" in text
    assert "MRK Negotiations" in text
    assert "Q2 2026" in text
    assert "Company-wide" in text
    assert "Annual planning" in text


def test_template_shows_none_open_when_empty(cfg):
    meeting = {"id": "x", "date": "2026-04-28", "summary": "Recap."}
    _, _, text = render_email(
        meeting, [{"owner": "Bob", "task": "Thing"}], [],
        subject_prefix="L10 Check-in",
        portal_name="L10 Weekly",
        portal_url="https://l10.sixpeakapps.com",
    )
    # Todos rendered, rocks section says (none open)
    assert "OPEN TO-DOS" in text
    assert "OPEN ROCKS" in text
    assert "(none open)" in text


# --- Pending-list filter tests --------------------------------------------


def test_skips_meeting_under_3_days(storage, cfg):
    _make_meeting(storage, days_ago=2)
    assert storage.list_meetings_pending_reminder(min_age_days=3, max_age_days=10) == []


def test_skips_meeting_over_10_days(storage, cfg):
    _make_meeting(storage, days_ago=11)
    assert storage.list_meetings_pending_reminder(min_age_days=3, max_age_days=10) == []


def test_pending_list_returns_due_meeting(storage, cfg):
    _make_meeting(storage, days_ago=3)
    pending = storage.list_meetings_pending_reminder(min_age_days=3, max_age_days=10)
    assert len(pending) == 1


def test_skips_meeting_with_blank_summary(storage, cfg):
    _make_meeting(storage, days_ago=3, summary="")
    assert storage.list_meetings_pending_reminder(min_age_days=3, max_age_days=10) == []


def test_skips_meeting_when_already_sent(storage, cfg):
    _make_meeting(storage, days_ago=3)
    storage.claim_reminder("l10_test")
    assert storage.list_meetings_pending_reminder(min_age_days=3, max_age_days=10) == []


def test_claim_is_idempotent(storage, cfg):
    _make_meeting(storage, days_ago=3)
    assert storage.claim_reminder("l10_test") is True
    assert storage.claim_reminder("l10_test") is False


# --- End-to-end run() ------------------------------------------------------


def test_skip_silently_when_no_open_todos_or_rocks(storage, cfg):
    _make_meeting(storage, days_ago=3)
    gmail = FakeGmail()
    cal = _calendar_with(["rak@sixpeakcapital.com"])
    result = run(storage=storage, cfg=cfg, dry_run=False,
                 gmail_service=gmail, calendar_service=cal)
    assert ("l10_test", "no open to-dos or rocks") in result["skipped"]
    assert result["sent"] == []
    m = storage.get_meeting("l10_test")
    assert m.get("_reminder_sent_at") is None


def test_rock_session_is_skipped(storage, cfg):
    """Quarterly Rock Sessions ride the L10 portal but are OFF the mid-cycle
    reminder rotation — skipped even with open to-dos and valid invitees."""
    _make_meeting(storage, days_ago=3, meeting_id="rock_q3",
                  kind="rock_session", title="Six Peak EOS — Q3 2026 Rock Session")
    _add_open_todo(storage, "Bob", "Thing")
    gmail = FakeGmail()
    cal = _calendar_with(["rak@sixpeakcapital.com"])
    result = run(storage=storage, cfg=cfg, dry_run=False,
                 gmail_service=gmail, calendar_service=cal)
    assert ("rock_q3", "rock session — reminders off") in result["skipped"]
    assert result["sent"] == []
    assert gmail.sent == []
    m = storage.get_meeting("rock_q3")
    assert m.get("_reminder_sent_at") is None


def test_weekly_l10_still_fires_alongside_rock_session(storage, cfg):
    """A rock session is skipped but a due weekly L10 still gets its reminder."""
    _make_meeting(storage, days_ago=3, meeting_id="rock_q3",
                  kind="rock_session", title="Six Peak EOS — Q3 2026 Rock Session")
    _make_meeting(storage, days_ago=4, meeting_id="weekly", kind="l10")
    _add_open_todo(storage, "Bob", "Thing")
    gmail = FakeGmail()
    cal = _calendar_with(["rak@sixpeakcapital.com"])
    result = run(storage=storage, cfg=cfg, dry_run=False,
                 gmail_service=gmail, calendar_service=cal)
    assert result["sent"] == ["weekly"]
    assert ("rock_q3", "rock session — reminders off") in result["skipped"]


def test_fires_when_only_todos_have_content(storage, cfg):
    _make_meeting(storage, days_ago=3)
    _add_open_todo(storage, "Bob", "Thing")
    gmail = FakeGmail()
    cal = _calendar_with(["rak@sixpeakcapital.com"])
    result = run(storage=storage, cfg=cfg, dry_run=False,
                 gmail_service=gmail, calendar_service=cal)
    assert result["sent"] == ["l10_test"]
    sent = gmail.sent[0]
    assert "OPEN TO-DOS" in sent["text"]
    assert "OPEN ROCKS" in sent["text"]
    rocks_idx = sent["text"].index("OPEN ROCKS")
    assert "(none open)" in sent["text"][rocks_idx:]


def test_fires_when_only_rocks_have_content(storage, cfg):
    _make_meeting(storage, days_ago=3)
    _add_open_rock(storage, "Bob Kennedy", "MRK Negotiations", due="Q2")
    gmail = FakeGmail()
    cal = _calendar_with(["rak@sixpeakcapital.com"])
    result = run(storage=storage, cfg=cfg, dry_run=False,
                 gmail_service=gmail, calendar_service=cal)
    assert result["sent"] == ["l10_test"]
    sent = gmail.sent[0]
    assert "Bob Kennedy" in sent["text"]
    assert "MRK Negotiations" in sent["text"]


def test_sends_reminder_with_both_todos_and_rocks(storage, cfg):
    _make_meeting(storage, days_ago=3)
    _add_open_todo(storage, "Chris Aiello", "Send the doc")
    _add_open_rock(storage, "Bob Kennedy", "MRK Negotiations", due="Q2 2026")
    _add_open_rock(storage, "Bob Kennedy", "300 Deharo")
    gmail = FakeGmail()
    cal = _calendar_with(["candresen@sixpeakcapital.com"])

    result = run(storage=storage, cfg=cfg, dry_run=False,
                 gmail_service=gmail, calendar_service=cal)

    assert result["sent"] == ["l10_test"]
    sent = gmail.sent[0]
    assert "L10 Check-in" in sent["subject"]
    assert "Send the doc" in sent["html"]
    assert "MRK Negotiations" in sent["html"]
    assert "300 Deharo" in sent["html"]
    assert "Q2 2026" in sent["html"]
    m = storage.get_meeting("l10_test")
    assert m["_reminder_sent_at"] is not None
    assert m["_reminder_log"]["open_todos_count"] == 1
    assert m["_reminder_log"]["open_rocks_owners"] == 1  # 1 owner (Bob with 2 rocks)


def test_completed_rocks_filtered_out(storage, cfg):
    _make_meeting(storage, days_ago=3)
    open_r = _add_open_rock(storage, "Bob", "Open rock")
    closed_r = _add_open_rock(storage, "Bob", "Closed rock")
    storage.toggle_rock(closed_r["id"])  # mark complete
    gmail = FakeGmail()
    cal = _calendar_with(["rak@sixpeakcapital.com"])
    run(storage=storage, cfg=cfg, dry_run=False,
        gmail_service=gmail, calendar_service=cal)
    sent = gmail.sent[0]
    assert "Open rock" in sent["text"]
    assert "Closed rock" not in sent["text"]


def test_dry_run_creates_draft_only_to_sender(storage, cfg):
    _make_meeting(storage, days_ago=3)
    _add_open_todo(storage, "Bob", "Thing")
    gmail = FakeGmail()
    cal = _calendar_with(["rak@sixpeakcapital.com"])
    result = run(storage=storage, cfg=cfg, dry_run=True,
                 gmail_service=gmail, calendar_service=cal)
    assert result["drafts"] == ["l10_test"]
    draft = gmail.created_drafts[0]
    assert draft["to"] == "cma@sixpeakcapital.com"
    assert draft["subject"].startswith("[DRY RUN]")
    # Non-consuming: no claim, no sent_at, no log — repeatable.
    m = storage.get_meeting("l10_test")
    assert m.get("_reminder_sent_at") is None
    assert m.get("_reminder_log") is None
    still_pending = storage.list_meetings_pending_reminder(min_age_days=3, max_age_days=10)
    assert any(x["id"] == "l10_test" for x in still_pending)


def test_preview_does_not_consume(storage, cfg):
    _make_meeting(storage, days_ago=3)
    _add_open_todo(storage, "Bob", "Thing")
    gmail = FakeGmail()
    cal = _calendar_with(["rak@sixpeakcapital.com"])
    result = run(storage=storage, cfg=cfg, dry_run=False, preview=True,
                 gmail_service=gmail, calendar_service=cal)
    assert result["sent"] == [] and result["drafts"] == []
    assert [w["meeting_id"] for w in result["would_send"]] == ["l10_test"]
    assert result["would_send"][0]["recipients"] == ["rak@sixpeakcapital.com"]
    assert gmail.sent == [] and gmail.created_drafts == []
    m = storage.get_meeting("l10_test")
    assert m.get("_reminder_sent_at") is None
    assert m.get("_reminder_log") is None


def test_preview_include_claimed_surfaces_blocked(storage, cfg):
    _make_meeting(storage, days_ago=3)
    _add_open_todo(storage, "Bob", "Thing")
    storage.claim_reminder("l10_test")
    cal = _calendar_with(["rak@sixpeakcapital.com"])
    default_preview = run(storage=storage, cfg=cfg, dry_run=False, preview=True,
                          gmail_service=FakeGmail(), calendar_service=cal)
    assert default_preview["would_send"] == []
    inclusive = run(storage=storage, cfg=cfg, dry_run=False, preview=True,
                    include_claimed=True, gmail_service=FakeGmail(), calendar_service=cal)
    assert [w["meeting_id"] for w in inclusive["would_send"]] == ["l10_test"]
    m = storage.get_meeting("l10_test")
    assert m.get("_reminder_sent_at") is not None  # still claimed, untouched


def test_no_calendar_invitees_skips_without_claiming(storage, cfg):
    _make_meeting(storage, days_ago=3)
    _add_open_todo(storage, "Bob", "Thing")
    gmail = FakeGmail()
    cal = FakeCalendar(return_empty=True)
    result = run(storage=storage, cfg=cfg, dry_run=False,
                 gmail_service=gmail, calendar_service=cal)
    assert ("l10_test", "no calendar invitees") in result["skipped"]
    m = storage.get_meeting("l10_test")
    assert m.get("_reminder_sent_at") is None


def test_send_failure_releases_claim(storage, cfg):
    _make_meeting(storage, days_ago=3)
    _add_open_todo(storage, "Bob", "Thing")
    gmail = FakeGmail()
    gmail.fail_on_send = True
    cal = _calendar_with(["rak@sixpeakcapital.com"])
    result = run(storage=storage, cfg=cfg, dry_run=False,
                 gmail_service=gmail, calendar_service=cal)
    assert len(result["errors"]) == 1
    m = storage.get_meeting("l10_test")
    assert m.get("_reminder_sent_at") is None


def test_link_points_to_main_portal_not_meeting_page(storage, cfg):
    _make_meeting(storage, days_ago=3)
    _add_open_todo(storage, "Bob", "Thing")
    gmail = FakeGmail()
    cal = _calendar_with(["rak@sixpeakcapital.com"])
    run(storage=storage, cfg=cfg, dry_run=False, gmail_service=gmail, calendar_service=cal)
    sent = gmail.sent[0]
    assert "https://l10.sixpeakapps.com" in sent["text"]
    assert "/meetings/" not in sent["text"]
    assert "/meetings/" not in sent["html"]


def test_excludes_sender_from_recipients(storage, cfg):
    _make_meeting(storage, days_ago=3)
    _add_open_todo(storage, "Bob", "Thing")
    gmail = FakeGmail()
    cal = _calendar_with(["cma@sixpeakcapital.com", "rak@sixpeakcapital.com"])
    run(storage=storage, cfg=cfg, dry_run=False, gmail_service=gmail, calendar_service=cal)
    assert gmail.sent[0]["to"] == "rak@sixpeakcapital.com"


def test_real_send_ccs_the_sender(storage, cfg):
    """Real sends CC the sender so Chris gets a copy in his inbox."""
    _make_meeting(storage, days_ago=3)
    _add_open_todo(storage, "Bob", "Thing")
    gmail = FakeGmail()
    cal = _calendar_with(["rak@sixpeakcapital.com"])
    run(storage=storage, cfg=cfg, dry_run=False, gmail_service=gmail, calendar_service=cal)
    assert gmail.sent[0]["cc"] == "cma@sixpeakcapital.com"


def test_dry_run_draft_has_no_cc(storage, cfg):
    """Drafts (dry-run) are addressed only to sender — no CC needed."""
    _make_meeting(storage, days_ago=3)
    _add_open_todo(storage, "Bob", "Thing")
    gmail = FakeGmail()
    cal = _calendar_with(["rak@sixpeakcapital.com"])
    run(storage=storage, cfg=cfg, dry_run=True, gmail_service=gmail, calendar_service=cal)
    assert gmail.created_drafts[0]["cc"] == ""


def test_run_with_no_pending_meetings(storage, cfg):
    gmail = FakeGmail()
    cal = FakeCalendar()
    result = run(storage=storage, cfg=cfg, dry_run=False,
                 gmail_service=gmail, calendar_service=cal)
    assert result == {"checked": 0, "sent": [], "drafts": [], "skipped": [], "errors": [], "would_send": []}
