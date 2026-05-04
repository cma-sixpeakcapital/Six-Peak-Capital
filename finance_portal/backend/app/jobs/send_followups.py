"""Follow-up email job — runs hourly via GitHub Actions cron.

Triggered by ``POST /api/jobs/send_followups`` (auth: PORTAL_API_KEY header).
For each meeting where:

  - ``followup_sent_at`` is NULL
  - 24h ≤ age(``data->>'saved_at'``) ≤ 7d
  - summary is non-empty

we look up the calendar event's invitee list, render an HTML email, and
send it via the Gmail API as ``cma@sixpeakcapital.com`` (refresh-token
auth). Idempotency is provided by an atomic claim on the meeting row;
on failure we release the claim so the next cron retries.

DRY_RUN mode writes to Gmail drafts addressed only to the sender — first
2 weeks of the rollout will run with DRY_RUN=true so Chris can review.
"""
from __future__ import annotations

import base64
import logging
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Callable, Protocol

from .email_template import render_email

log = logging.getLogger(__name__)

# Gmail API scopes — gmail.send + gmail.compose (drafts) for sending,
# calendar.readonly for reading the recurring event's instances.
SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/calendar.readonly",
]


# --- Service builders (real OAuth path; tests inject fakes instead) -------

def build_google_credentials(cfg) -> Any:
    """Build a refresh-token Credentials object. Lazy import so tests
    don't need google-auth installed.
    """
    from google.oauth2.credentials import Credentials

    return Credentials(
        token=None,
        refresh_token=cfg.google_refresh_token,
        client_id=cfg.google_client_id,
        client_secret=cfg.google_client_secret,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=SCOPES,
    )


def build_gmail_service(cfg) -> Any:
    from googleapiclient.discovery import build

    return build("gmail", "v1", credentials=build_google_credentials(cfg), cache_discovery=False)


def build_calendar_service(cfg) -> Any:
    from googleapiclient.discovery import build

    return build("calendar", "v3", credentials=build_google_credentials(cfg), cache_discovery=False)


# --- Calendar invitee lookup ----------------------------------------------

def _find_instance_via_instances(cal_service: Any, calendar_id: str,
                                  recurring_event_id: str,
                                  time_min: str, time_max: str) -> dict[str, Any] | None:
    """Primary lookup path: events.instances(eventId=master).

    Real API errors (auth, network, etc.) bubble up to the caller, which
    treats them as run-level errors. An empty ``items`` list (e.g. expired
    RRULE) returns None so the caller can try the fallback.
    """
    result = cal_service.events().instances(
        calendarId=calendar_id,
        eventId=recurring_event_id,
        timeMin=time_min,
        timeMax=time_max,
        maxResults=5,
        showDeleted=False,
    ).execute()
    items = result.get("items", []) if isinstance(result, dict) else []
    for inst in items:
        if inst.get("status") == "cancelled":
            continue
        return inst
    return None


def _find_instance_via_list_scan(cal_service: Any, calendar_id: str,
                                  recurring_event_id: str,
                                  time_min: str, time_max: str) -> dict[str, Any] | None:
    """Fallback lookup: events.list with the day window, then filter for
    events whose id or recurringEventId references our master event.

    Needed when the master recurrence has an expired UNTIL clause; Google
    refuses to expand instances after that date even though the events
    physically exist on the calendar.
    """
    result = cal_service.events().list(
        calendarId=calendar_id,
        timeMin=time_min,
        timeMax=time_max,
        singleEvents=True,
        maxResults=50,
        showDeleted=False,
    ).execute()
    for evt in result.get("items", []) or []:
        if evt.get("status") == "cancelled":
            continue
        eid = evt.get("id", "") or ""
        rid = evt.get("recurringEventId", "") or ""
        if eid.startswith(recurring_event_id + "_") or rid.startswith(recurring_event_id):
            return evt
    return None


def lookup_invitees(cal_service: Any, *, calendar_id: str, recurring_event_id: str,
                    meeting_date: str, sender_email: str) -> list[str]:
    """Find the calendar instance for this meeting date and extract the
    invitee email list. Excludes the sender (they're the From: address) so
    Chris doesn't email himself, and skips declines, resources, and the
    organizer's "self" attendee entry.

    Returns [] if no instance is found — caller should treat as "skip and
    retry next cron" rather than swallowing.

    Two-stage lookup:
      1. ``events.instances(eventId)`` — fast, the canonical path.
      2. Fallback: ``events.list(timeMin, timeMax, singleEvents=True)`` and
         filter for events whose ``id`` or ``recurringEventId`` references our
         master event. This handles the edge case where the recurring rule
         has an UNTIL clause in the past but individual instances still exist
         (Google's instances() API treats those as "expired" and returns
         empty even though the events are clearly on the calendar).
    """
    if not recurring_event_id or not meeting_date:
        return []
    # Validate the date format before sending it to the API.
    try:
        datetime.strptime(meeting_date, "%Y-%m-%d")
    except ValueError:
        return []
    # Window the meeting day in UTC; the Calendar API returns the recurring
    # instance whose start falls in this range.
    time_min = f"{meeting_date}T00:00:00Z"
    time_max = f"{meeting_date}T23:59:59Z"

    instance = _find_instance_via_instances(
        cal_service, calendar_id, recurring_event_id, time_min, time_max
    )
    if instance is None:
        instance = _find_instance_via_list_scan(
            cal_service, calendar_id, recurring_event_id, time_min, time_max
        )
    if instance is None:
        return []

    sender_lower = (sender_email or "").lower()
    out: list[str] = []
    seen: set[str] = set()
    for a in instance.get("attendees", []) or []:
        if a.get("responseStatus") == "declined":
            continue
        if a.get("resource"):
            continue
        if a.get("self"):
            # The organizer's own entry — skip; we're sending FROM them.
            continue
        email = (a.get("email") or "").strip()
        if not email:
            continue
        if email.lower() == sender_lower:
            continue
        if email.lower() in seen:
            continue
        seen.add(email.lower())
        out.append(email)
    return out


# --- Gmail send / draft ---------------------------------------------------

def _build_mime(sender: str, to: list[str], subject: str, html: str, text: str) -> str:
    """Build a base64url-encoded MIME multipart/alternative message."""
    msg = MIMEMultipart("alternative")
    msg["From"] = sender
    msg["To"] = ", ".join(to) if to else sender
    msg["Subject"] = subject
    msg.attach(MIMEText(text, "plain", _charset="utf-8"))
    msg.attach(MIMEText(html, "html", _charset="utf-8"))
    return base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")


def send_email(gmail_service: Any, *, sender: str, to: list[str],
               subject: str, html: str, text: str) -> str:
    """Send via Gmail API. Returns the Gmail message ID."""
    raw = _build_mime(sender, to, subject, html, text)
    sent = gmail_service.users().messages().send(
        userId="me", body={"raw": raw}
    ).execute()
    return sent.get("id", "")


def create_draft(gmail_service: Any, *, sender: str, subject: str,
                 html: str, text: str) -> str:
    """Create a Gmail draft addressed only to the sender (DRY_RUN path)."""
    raw = _build_mime(sender, [sender], subject, html, text)
    draft = gmail_service.users().drafts().create(
        userId="me", body={"message": {"raw": raw}}
    ).execute()
    return draft.get("id", "")


# --- Top-level entry ------------------------------------------------------

class _CfgLike(Protocol):
    google_calendar_id: str
    followup_cal_event_id: str
    followup_sender_email: str
    followup_subject_prefix: str
    followup_portal_name: str
    followup_portal_url: str
    followup_cadence: str
    followup_min_age_hours: int
    followup_max_age_days: int


@dataclass
class RunResult:
    checked: int = 0
    sent: list[str] | None = None
    drafts: list[str] | None = None
    skipped: list[tuple[str, str]] | None = None
    errors: list[tuple[str, str]] | None = None

    def __post_init__(self):
        self.sent = self.sent or []
        self.drafts = self.drafts or []
        self.skipped = self.skipped or []
        self.errors = self.errors or []

    def to_dict(self) -> dict[str, Any]:
        return {
            "checked": self.checked,
            "sent": self.sent,
            "drafts": self.drafts,
            "skipped": self.skipped,
            "errors": self.errors,
        }


def run(
    *,
    storage: Any,
    cfg: _CfgLike,
    dry_run: bool,
    gmail_service: Any | None = None,
    calendar_service: Any | None = None,
    open_todos_provider: Callable[[], list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Process all due meetings.

    All external dependencies (Gmail, Calendar, todos source) can be
    injected — production passes None and the real services are built.
    Tests pass fakes.
    """
    pending = storage.list_meetings_pending_followup(
        min_age_hours=cfg.followup_min_age_hours,
        max_age_days=cfg.followup_max_age_days,
    )
    result = RunResult(checked=len(pending))
    if not pending:
        return result.to_dict()

    if calendar_service is None:
        calendar_service = build_calendar_service(cfg)
    if gmail_service is None:
        gmail_service = build_gmail_service(cfg)

    if open_todos_provider is None:
        open_todos_provider = lambda: [
            t for t in storage.list_todos() if not t.get("completed")
        ]
    open_todos = open_todos_provider()

    for meeting in pending:
        meeting_id = meeting.get("id", "")
        try:
            recipients = lookup_invitees(
                calendar_service,
                calendar_id=cfg.google_calendar_id,
                recurring_event_id=cfg.followup_cal_event_id,
                meeting_date=meeting.get("date", ""),
                sender_email=cfg.followup_sender_email,
            )
            if not recipients:
                result.skipped.append((meeting_id, "no calendar invitees"))
                log.warning("send_followups: no invitees for meeting %s — will retry next cycle", meeting_id)
                continue

            subject, html, text = render_email(
                meeting,
                open_todos,
                subject_prefix=cfg.followup_subject_prefix,
                portal_name=cfg.followup_portal_name,
                portal_url=cfg.followup_portal_url,
                cadence=cfg.followup_cadence,
            )

            if not storage.claim_followup(meeting_id):
                result.skipped.append((meeting_id, "already claimed"))
                continue

            try:
                if dry_run:
                    gmail_id = create_draft(
                        gmail_service,
                        sender=cfg.followup_sender_email,
                        subject=f"[DRY RUN] {subject}",
                        html=html,
                        text=text,
                    )
                    result.drafts.append(meeting_id)
                else:
                    gmail_id = send_email(
                        gmail_service,
                        sender=cfg.followup_sender_email,
                        to=recipients,
                        subject=subject,
                        html=html,
                        text=text,
                    )
                    result.sent.append(meeting_id)
                storage.record_followup_log(meeting_id, {
                    "sent_at": datetime.now(timezone.utc).isoformat(),
                    "recipients": recipients,
                    "dry_run": dry_run,
                    "gmail_id": gmail_id,
                })
            except Exception as exc:
                # Mid-send failure: release the claim so we retry next cycle.
                storage.record_followup_log(meeting_id, {
                    "attempted_at": datetime.now(timezone.utc).isoformat(),
                    "error": f"{type(exc).__name__}: {exc}",
                    "traceback": traceback.format_exc(),
                })
                storage.release_followup(meeting_id)
                raise

        except Exception as exc:
            log.exception("send_followups: error processing meeting %s", meeting_id)
            result.errors.append((meeting_id, f"{type(exc).__name__}: {exc}"))
            continue

    return result.to_dict()
