"""Render the Finance mid-cycle reminder email — pure functions, no I/O.

Returns ``(subject, html, plaintext)``. Tone is deliberately automated —
this is a system-generated reminder of open to-dos and goals heading into
the next monthly Finance call, not a personal note. The header makes that
explicit so recipients don't reply expecting Chris on the other end.

Used only by sp-finance — L10 (weekly) and LV Exec (bi-weekly) don't get
a mid-cycle reminder because their cadences are too tight to need one.
"""
from __future__ import annotations

from datetime import date as date_cls, datetime
from html import escape
from typing import Any

from dateutil.relativedelta import relativedelta

from .email_template import (
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


# --- Rendering helpers ---------------------------------------------------


def _open_goals(goals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter goals down to those still incomplete. Goals are a flat list
    on Finance — no per-person grouping (unlike to-dos)."""
    return [g for g in (goals or []) if (g.get("status") or "").lower() != "complete"]


# --- HTML and plaintext rendering ----------------------------------------


def render_html(meeting: dict[str, Any], open_todos: list[dict[str, Any]],
                open_goals: list[dict[str, Any]],
                portal_name: str, portal_url: str) -> str:
    parts: list[str] = []
    next_call = estimated_next_call(meeting.get("date", ""))
    parts.append(
        f"<p>Automated reminder — heading into the next "
        f"{escape(portal_name)} call on {escape(next_call)}. Below are the "
        f"open to-dos and goals still on the list:</p>"
    )

    parts.append("<p><b>OPEN TO-DOS</b></p>")
    if open_todos:
        for owner, items in _todos_grouped_by_owner(open_todos):
            parts.append(f"<p><i>{escape(owner)}</i></p>")
            parts.append("<ul>")
            for t in items:
                task = (t.get("task") or "").strip()
                due = (t.get("due") or "").strip()
                tail = f" <i>({escape(due)})</i>" if due else ""
                parts.append(f"  <li>{escape(task)}{tail}</li>")
            parts.append("</ul>")
    else:
        parts.append("<p><i>(none open)</i></p>")

    parts.append("<p><b>OPEN GOALS</b></p>")
    if open_goals:
        parts.append("<ul>")
        for g in open_goals:
            title = (g.get("title") or "").strip()
            due = (g.get("due") or "").strip()
            tail = f" <i>({escape(due)})</i>" if due else ""
            parts.append(f"  <li>{escape(title)}{tail}</li>")
        parts.append("</ul>")
    else:
        parts.append("<p><i>(none open)</i></p>")

    # Link to the portal's main page (the to-do/goal list view), not the
    # meeting detail page. The reminder is forward-looking ("update your
    # status before the next call") so the to-do landing page is the right
    # destination.
    portal_link = portal_url.rstrip("/")
    parts.append(
        f'<p>Update your status in the portal: <a href="{escape(portal_link)}">'
        f"{escape(portal_link)}</a></p>"
    )
    parts.append(
        "<p style='color:#888;font-size:12px;'>"
        "— sent automatically by the portal. Do not reply.</p>"
    )

    return "\n".join(parts)


def render_text(meeting: dict[str, Any], open_todos: list[dict[str, Any]],
                open_goals: list[dict[str, Any]],
                portal_name: str, portal_url: str) -> str:
    lines: list[str] = []
    next_call = estimated_next_call(meeting.get("date", ""))
    lines.append(
        f"Automated reminder — heading into the next {portal_name} call "
        f"on {next_call}. Below are the open to-dos and goals still on "
        f"the list:"
    )
    lines.append("")

    lines.append("OPEN TO-DOS")
    if open_todos:
        for owner, items in _todos_grouped_by_owner(open_todos):
            lines.append(f"  {owner}")
            for t in items:
                task = (t.get("task") or "").strip()
                due = (t.get("due") or "").strip()
                tail = f" ({due})" if due else ""
                lines.append(f"    - {task}{tail}")
    else:
        lines.append("  (none open)")
    lines.append("")

    lines.append("OPEN GOALS")
    if open_goals:
        for g in open_goals:
            title = (g.get("title") or "").strip()
            due = (g.get("due") or "").strip()
            tail = f" ({due})" if due else ""
            lines.append(f"  - {title}{tail}")
    else:
        lines.append("  (none open)")
    lines.append("")

    portal_link = portal_url.rstrip("/")
    lines.append(f"Update your status in the portal: {portal_link}")
    lines.append("")
    lines.append("— sent automatically by the portal. Do not reply.")

    return "\n".join(lines)


def render_email(meeting: dict[str, Any], open_todos: list[dict[str, Any]],
                 open_goals: list[dict[str, Any]],
                 *, subject_prefix: str, portal_name: str,
                 portal_url: str) -> tuple[str, str, str]:
    """Top-level: returns (subject, html_body, text_body).

    Caller should ensure at least one of ``open_todos`` or ``open_goals`` is
    non-empty — this renderer doesn't skip-when-empty itself (it'll show
    "(none open)" in both sections). See ``send_reminders.run`` for the
    silent-skip-when-both-empty filter.
    """
    subject = render_subject(subject_prefix, meeting)
    html = render_html(meeting, open_todos, open_goals, portal_name, portal_url)
    text = render_text(meeting, open_todos, open_goals, portal_name, portal_url)
    return subject, html, text
