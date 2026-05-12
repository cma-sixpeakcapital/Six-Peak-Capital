"""Render the Finance mid-cycle reminder email — pure functions, no I/O.

Returns ``(subject, html, plaintext)``. Same shape as ``email_template.py``
for the follow-up recap, but the body focuses purely on OPEN TO-DOS with a
short intro framing it as a check-in between monthly Finance calls.

Used only by sp-finance — L10 (weekly) and LV Exec (bi-weekly) don't get
a mid-cycle reminder because their cadences are too tight to need one.
"""
from __future__ import annotations

from datetime import date as date_cls, datetime
from html import escape
from typing import Any

from dateutil.relativedelta import relativedelta

from app.jobs.email_template import (
    _owner_or_unassigned,
    _todos_grouped_by_owner,
    nice_date,
)


def _parse_meeting_date(meeting_date: str | date_cls) -> date_cls | None:
    if isinstance(meeting_date, date_cls):
        return meeting_date
    try:
        return datetime.strptime(str(meeting_date), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def estimated_next_call(meeting_date: str | date_cls) -> str:
    """For a monthly cadence, estimate the next call as +1 calendar month.

    relativedelta(months=1) handles month boundaries (Jan 31 → Feb 28/29)
    cleanly. Returns a display string like 'May 28'. Falls back to '~4 weeks
    from now' if the input doesn't parse.
    """
    d = _parse_meeting_date(meeting_date)
    if d is None:
        return "in ~4 weeks"
    next_d = d + relativedelta(months=1)
    return next_d.strftime("%B {day}").replace("{day}", str(next_d.day))


def render_subject(prefix: str, meeting: dict[str, Any]) -> str:
    """Subject like 'Finance Check-in — open items 2 weeks before next call'.

    Deliberately doesn't include the meeting date — the email is forward-
    looking (about the next call), not retrospective (about the last one).
    """
    return f"{prefix} — open items 2 weeks before next call"


def render_html(meeting: dict[str, Any], open_todos: list[dict[str, Any]],
                portal_url: str) -> str:
    parts: list[str] = []
    parts.append("<p>Team —</p>")
    last_call = nice_date(meeting.get("date", ""))
    next_call = estimated_next_call(meeting.get("date", ""))
    parts.append(
        f"<p>Quick check-in — it's been ~2 weeks since our "
        f"{escape(last_call)} Finance call and about 2 weeks until the next "
        f"one ({escape(next_call)}). Open items still on the list:</p>"
    )

    parts.append("<p><b>OPEN TO-DOS</b></p>")
    for owner, items in _todos_grouped_by_owner(open_todos):
        parts.append(f"<p><i>{escape(owner)}</i></p>")
        parts.append("<ul>")
        for t in items:
            task = (t.get("task") or "").strip()
            due = (t.get("due") or "").strip()
            tail = f" <i>({escape(due)})</i>" if due else ""
            parts.append(f"  <li>{escape(task)}{tail}</li>")
        parts.append("</ul>")

    parts.append(
        "<p>If anything's blocked or needs discussion before next call, "
        "reply here.</p>"
    )

    # Link to the portal's main page (the to-do list view), not the meeting
    # detail page. The reminder is forward-looking ("update your status before
    # the next call") so the to-do landing page is the relevant destination.
    portal_link = portal_url.rstrip("/")
    parts.append(
        f'<p>Update your to-dos in the portal: <a href="{escape(portal_link)}">'
        f"{escape(portal_link)}</a></p>"
    )
    parts.append("<p>— Chris</p>")

    return "\n".join(parts)


def render_text(meeting: dict[str, Any], open_todos: list[dict[str, Any]],
                portal_url: str) -> str:
    lines: list[str] = []
    lines.append("Team —")
    lines.append("")
    last_call = nice_date(meeting.get("date", ""))
    next_call = estimated_next_call(meeting.get("date", ""))
    lines.append(
        f"Quick check-in — it's been ~2 weeks since our {last_call} Finance "
        f"call and about 2 weeks until the next one ({next_call}). Open "
        f"items still on the list:"
    )
    lines.append("")

    lines.append("OPEN TO-DOS")
    for owner, items in _todos_grouped_by_owner(open_todos):
        lines.append(f"  {owner}")
        for t in items:
            task = (t.get("task") or "").strip()
            due = (t.get("due") or "").strip()
            tail = f" ({due})" if due else ""
            lines.append(f"    - {task}{tail}")
    lines.append("")

    lines.append(
        "If anything's blocked or needs discussion before next call, reply here."
    )
    lines.append("")

    portal_link = portal_url.rstrip("/")
    lines.append(f"Update your to-dos in the portal: {portal_link}")
    lines.append("")
    lines.append("— Chris")

    return "\n".join(lines)


def render_email(meeting: dict[str, Any], open_todos: list[dict[str, Any]],
                 *, subject_prefix: str, portal_url: str) -> tuple[str, str, str]:
    """Top-level: returns (subject, html_body, text_body).

    Caller should ensure ``open_todos`` is non-empty — this renderer assumes
    there's something to nudge about. See ``send_reminders.run`` for the
    silent-skip-when-empty filter.
    """
    subject = render_subject(subject_prefix, meeting)
    html = render_html(meeting, open_todos, portal_url)
    text = render_text(meeting, open_todos, portal_url)
    return subject, html, text
