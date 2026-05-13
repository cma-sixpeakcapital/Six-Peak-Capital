"""Mid-cycle reminder email job — runs hourly via GitHub Actions cron.

Triggered by ``POST /api/jobs/send_reminders`` (auth: PORTAL_API_KEY header).
For each Finance meeting where:

  - ``reminder_sent_at`` is NULL
  - 14d ≤ (today - meeting.date) ≤ 21d
  - summary is non-empty
  - there's at least one open to-do OR open goal (silent-skip when both empty)

we look up the calendar event's invitee list, render the mid-cycle reminder
email, and send it via the Gmail API as cma@sixpeakcapital.com. Idempotency
via atomic ``claim_reminder`` on the meeting row; on failure the claim is
released so the next cron retries (until the 21-day cutoff).

Almost everything is reused from ``send_followups.py`` — same OAuth creds,
same Gmail/Calendar service builders, same MIME helpers, same invitee
filter. Only the SQL filter, the template, and the column names differ.
"""
from __future__ import annotations

import logging
import traceback
from datetime import datetime, timezone
from typing import Any, Callable, Protocol

from .reminder_template import render_email, _open_goals
from .send_followups import (
    build_calendar_service,
    build_gmail_service,
    create_draft,
    lookup_invitees,
    send_email,
)

log = logging.getLogger(__name__)


class _CfgLike(Protocol):
    google_calendar_id: str
    followup_cal_event_id: str
    followup_sender_email: str
    followup_portal_name: str
    followup_portal_url: str
    followup_reminder_subject_prefix: str
    followup_reminder_min_age_days: int
    followup_reminder_max_age_days: int


def run(
    *,
    storage: Any,
    cfg: _CfgLike,
    dry_run: bool,
    gmail_service: Any | None = None,
    calendar_service: Any | None = None,
    open_todos_provider: Callable[[], list[dict[str, Any]]] | None = None,
    open_goals_provider: Callable[[], list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Process all due reminders.

    Same dependency-injection shape as send_followups.run — tests pass
    fakes; production passes None and the real services are built.
    """
    pending = storage.list_meetings_pending_reminder(
        min_age_days=cfg.followup_reminder_min_age_days,
        max_age_days=cfg.followup_reminder_max_age_days,
    )
    result: dict[str, Any] = {
        "checked": len(pending),
        "sent": [],
        "drafts": [],
        "skipped": [],
        "errors": [],
    }
    if not pending:
        return result

    if calendar_service is None:
        calendar_service = build_calendar_service(cfg)
    if gmail_service is None:
        gmail_service = build_gmail_service(cfg)

    if open_todos_provider is None:
        open_todos_provider = lambda: [
            t for t in storage.list_todos() if not t.get("completed")
        ]
    if open_goals_provider is None:
        # Finance stores goals on storage.list_goals(); fall back to [] for
        # storage backends that don't have it (test fixtures, other portals).
        def _default_goals() -> list[dict[str, Any]]:
            lister = getattr(storage, "list_goals", None)
            if lister is None:
                return []
            return _open_goals(lister())
        open_goals_provider = _default_goals

    for meeting in pending:
        meeting_id = meeting.get("id", "")
        try:
            # Silent skip if both lists are empty — no point nudging about
            # nothing. Doesn't claim, so we won't re-check this meeting
            # until the next hourly run; once past the 21-day cutoff it
            # falls out of the pending list anyway.
            open_todos = open_todos_provider()
            open_goals = open_goals_provider()
            if not open_todos and not open_goals:
                result["skipped"].append((meeting_id, "no open to-dos or goals"))
                continue

            recipients = lookup_invitees(
                calendar_service,
                calendar_id=cfg.google_calendar_id,
                recurring_event_id=cfg.followup_cal_event_id,
                meeting_date=meeting.get("date", ""),
                sender_email=cfg.followup_sender_email,
            )
            if not recipients:
                result["skipped"].append((meeting_id, "no calendar invitees"))
                log.warning(
                    "send_reminders: no invitees for meeting %s — will retry next cycle",
                    meeting_id,
                )
                continue

            subject, html, text = render_email(
                meeting,
                open_todos,
                open_goals,
                subject_prefix=cfg.followup_reminder_subject_prefix,
                portal_name=cfg.followup_portal_name,
                portal_url=cfg.followup_portal_url,
            )

            if not storage.claim_reminder(meeting_id):
                result["skipped"].append((meeting_id, "already claimed"))
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
                    result["drafts"].append(meeting_id)
                else:
                    # CC the sender (Chris) so he gets a copy in his inbox.
                    gmail_id = send_email(
                        gmail_service,
                        sender=cfg.followup_sender_email,
                        to=recipients,
                        subject=subject,
                        html=html,
                        text=text,
                        cc=[cfg.followup_sender_email] if cfg.followup_sender_email else None,
                    )
                    result["sent"].append(meeting_id)
                storage.record_reminder_log(meeting_id, {
                    "sent_at": datetime.now(timezone.utc).isoformat(),
                    "recipients": recipients,
                    "dry_run": dry_run,
                    "gmail_id": gmail_id,
                    "open_todos_count": len(open_todos),
                    "open_goals_count": len(open_goals),
                })
            except Exception as exc:
                storage.record_reminder_log(meeting_id, {
                    "attempted_at": datetime.now(timezone.utc).isoformat(),
                    "error": f"{type(exc).__name__}: {exc}",
                    "traceback": traceback.format_exc(),
                })
                storage.release_reminder(meeting_id)
                raise

        except Exception as exc:
            log.exception("send_reminders: error processing meeting %s", meeting_id)
            result["errors"].append((meeting_id, f"{type(exc).__name__}: {exc}"))
            continue

    return result
