"""Render the L10 mid-cycle reminder email — pure functions, no I/O.

Returns ``(subject, html, plaintext)``. Tone is deliberately automated —
this is a system-generated reminder of open to-dos and rocks heading into
the next weekly L10 call, not a personal note. The header makes that
explicit so recipients don't reply expecting Chris on the other end.
"""
from __future__ import annotations

from datetime import date as date_cls, datetime, timedelta
from html import escape
from itertools import groupby
from typing import Any

from .email_template import (
    _owner_or_unassigned,
    _todos_grouped_by_owner,
)


def _parse_meeting_date(meeting_date: str | date_cls) -> date_cls | None:
    if isinstance(meeting_date, date_cls):
        return meeting_date
    try:
        return datetime.strptime(str(meeting_date), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def estimated_next_call(meeting_date: str | date_cls) -> str:
    """For a weekly cadence, estimate the next call as +7 days.

    Returns a display string like 'May 12'. Falls back to '~1 week from now'
    if the input doesn't parse.
    """
    d = _parse_meeting_date(meeting_date)
    if d is None:
        return "in ~1 week"
    next_d = d + timedelta(days=7)
    return next_d.strftime("%B {day}").replace("{day}", str(next_d.day))


def render_subject(prefix: str, meeting: dict[str, Any]) -> str:
    """Subject like 'L10 Check-in — open items before next call'."""
    return f"{prefix} — open items before next call"


# --- Rocks rendering -----------------------------------------------------


def open_rocks_by_owner(rocks_doc: dict[str, Any]) -> list[tuple[str, list[dict[str, Any]]]]:
    """Extract open (status != 'complete') rocks from the rocks_doc.

    L10's rocks live as ``{owner_name: [rock, ...]}`` plus a separate
    flat ``company_rocks`` list. We return a single ordered list of
    (owner, rocks) tuples — per-person owners first (alphabetical),
    then 'Company-wide' if there are any open company rocks.
    """
    out: list[tuple[str, list[dict[str, Any]]]] = []
    personal: dict[str, list[dict[str, Any]]] = {}
    for owner, rocks in (rocks_doc.get("rocks") or {}).items():
        open_rocks = [r for r in (rocks or []) if (r.get("status") or "").lower() != "complete"]
        if open_rocks:
            personal[_owner_or_unassigned(owner)] = open_rocks
    for owner in sorted(personal.keys(), key=str.lower):
        out.append((owner, personal[owner]))

    company_open = [r for r in (rocks_doc.get("company_rocks") or [])
                    if (r.get("status") or "").lower() != "complete"]
    if company_open:
        out.append(("Company-wide", company_open))
    return out


# --- HTML and plaintext rendering ----------------------------------------


def render_html(meeting: dict[str, Any], open_todos: list[dict[str, Any]],
                rocks_by_owner: list[tuple[str, list[dict[str, Any]]]],
                portal_name: str, portal_url: str) -> str:
    parts: list[str] = []
    next_call = estimated_next_call(meeting.get("date", ""))
    parts.append(
        f"<p>Automated reminder — heading into the next {escape(portal_name)} "
        f"call on {escape(next_call)}. Below are the open to-dos and rocks "
        f"still on the list:</p>"
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

    parts.append("<p><b>OPEN ROCKS</b></p>")
    if rocks_by_owner:
        for owner, rocks in rocks_by_owner:
            parts.append(f"<p><i>{escape(owner)}</i></p>")
            parts.append("<ul>")
            for r in rocks:
                title = (r.get("title") or "").strip()
                due = (r.get("due") or "").strip()
                tail = f" <i>({escape(due)})</i>" if due else ""
                parts.append(f"  <li>{escape(title)}{tail}</li>")
            parts.append("</ul>")
    else:
        parts.append("<p><i>(none open)</i></p>")

    # Link to the portal's main page (the to-do/rocks list view), not the
    # meeting detail page. Reminder is forward-looking.
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
                rocks_by_owner: list[tuple[str, list[dict[str, Any]]]],
                portal_name: str, portal_url: str) -> str:
    lines: list[str] = []
    next_call = estimated_next_call(meeting.get("date", ""))
    lines.append(
        f"Automated reminder — heading into the next {portal_name} call "
        f"on {next_call}. Below are the open to-dos and rocks still on "
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

    lines.append("OPEN ROCKS")
    if rocks_by_owner:
        for owner, rocks in rocks_by_owner:
            lines.append(f"  {owner}")
            for r in rocks:
                title = (r.get("title") or "").strip()
                due = (r.get("due") or "").strip()
                tail = f" ({due})" if due else ""
                lines.append(f"    - {title}{tail}")
    else:
        lines.append("  (none open)")
    lines.append("")

    portal_link = portal_url.rstrip("/")
    lines.append(f"Update your status in the portal: {portal_link}")
    lines.append("")
    lines.append("— sent automatically by the portal. Do not reply.")

    return "\n".join(lines)


def render_email(meeting: dict[str, Any], open_todos: list[dict[str, Any]],
                 rocks_by_owner: list[tuple[str, list[dict[str, Any]]]],
                 *, subject_prefix: str, portal_name: str,
                 portal_url: str) -> tuple[str, str, str]:
    """Top-level: returns (subject, html_body, text_body).

    Caller should ensure at least one of ``open_todos`` or ``rocks_by_owner``
    is non-empty. See ``send_reminders.run`` for the skip-when-both-empty
    filter.
    """
    subject = render_subject(subject_prefix, meeting)
    html = render_html(meeting, open_todos, rocks_by_owner, portal_name, portal_url)
    text = render_text(meeting, open_todos, rocks_by_owner, portal_name, portal_url)
    return subject, html, text
