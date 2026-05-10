"""Render the follow-up recap email — pure functions, no I/O.

Returns ``(subject, html, plaintext)``. The ``html`` part is what most
recipients will see; the plaintext is the multipart/alternative fallback.
"""
from __future__ import annotations

from datetime import date as date_cls, datetime
from html import escape
from itertools import groupby
from typing import Any, Iterable

from app.storage import bullet_split


CADENCE_WORD = {
    "weekly": "WEEK",
    "biweekly": "CYCLE",
    "bi-weekly": "CYCLE",
    "monthly": "MONTH",
}


def cycle_word(cadence: str) -> str:
    return CADENCE_WORD.get((cadence or "").lower(), "CYCLE")


def nice_date(meeting_date: str | date_cls) -> str:
    """Render a YYYY-MM-DD as 'Tuesday, April 28'.

    Falls back to the raw string if parsing fails — meetings should always
    have a valid date but never assume.
    """
    if isinstance(meeting_date, date_cls):
        d = meeting_date
    else:
        try:
            d = datetime.strptime(str(meeting_date), "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return str(meeting_date)
    return d.strftime("%A, %B {day}").replace("{day}", str(d.day))


def _owner_or_unassigned(owner: str | None) -> str:
    return (owner or "").strip() or "Unassigned"


def _todos_grouped_by_owner(todos: Iterable[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
    """Sort by owner (case-insensitive), then group. Stable across runs."""
    items = sorted(todos, key=lambda t: _owner_or_unassigned(t.get("owner")).lower())
    groups: list[tuple[str, list[dict[str, Any]]]] = []
    for owner, items_in_group in groupby(items, key=lambda t: _owner_or_unassigned(t.get("owner"))):
        groups.append((owner, list(items_in_group)))
    return groups


def render_subject(prefix: str, meeting: dict[str, Any]) -> str:
    title = (meeting.get("title") or "").strip()
    suffix = f" ({title})" if title else ""
    return f"{prefix} — {meeting.get('date', '')}{suffix}"


def render_html(meeting: dict[str, Any], open_todos: list[dict[str, Any]],
                portal_name: str, portal_url: str, cadence: str) -> str:
    """HTML body — uses inline tags so it renders in Gmail / Outlook without external CSS."""
    parts: list[str] = []
    parts.append("<p>Team —</p>")
    parts.append(
        f"<p>Recap from {escape(nice_date(meeting.get('date', '')))}'s {escape(portal_name)}:</p>"
    )

    parts.append("<p><b>WHAT WE COVERED</b></p>")
    bullets = bullet_split(meeting.get("summary", "") or "")
    if bullets:
        parts.append("<ul>")
        for b in bullets:
            parts.append(f"  <li>{escape(b)}</li>")
        parts.append("</ul>")
    else:
        parts.append("<p><i>(no summary available)</i></p>")

    parts.append("<p><b>ACTION ITEMS FROM THIS MEETING</b></p>")
    action_items = meeting.get("action_items") or []
    if action_items:
        parts.append("<ul>")
        for ai in action_items:
            owner = _owner_or_unassigned(ai.get("owner"))
            task = (ai.get("task") or ai.get("text") or "").strip()
            parts.append(f"  <li><b>{escape(owner)}</b> — {escape(task)}</li>")
        parts.append("</ul>")
    else:
        parts.append("<p><i>(no action items from this meeting)</i></p>")

    parts.append(f"<p><b>OPEN TO-DOS HEADING INTO NEXT {cycle_word(cadence)}</b></p>")
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
        parts.append("<p><i>(no open to-dos)</i></p>")

    portal_link = f"{portal_url.rstrip('/')}/meetings/{meeting.get('id', '')}"
    parts.append(
        f'<p>Full portal view: <a href="{escape(portal_link)}">{escape(portal_link)}</a></p>'
    )
    parts.append("<p>— Chris</p>")

    return "\n".join(parts)


def render_text(meeting: dict[str, Any], open_todos: list[dict[str, Any]],
                portal_name: str, portal_url: str, cadence: str) -> str:
    """Plain-text alternative. Same content, no HTML."""
    lines: list[str] = []
    lines.append("Team —")
    lines.append("")
    lines.append(f"Recap from {nice_date(meeting.get('date', ''))}'s {portal_name}:")
    lines.append("")
    lines.append("WHAT WE COVERED")
    bullets = bullet_split(meeting.get("summary", "") or "")
    if bullets:
        for b in bullets:
            lines.append(f"  - {b}")
    else:
        lines.append("  (no summary available)")
    lines.append("")

    lines.append("ACTION ITEMS FROM THIS MEETING")
    action_items = meeting.get("action_items") or []
    if action_items:
        for ai in action_items:
            owner = _owner_or_unassigned(ai.get("owner"))
            task = (ai.get("task") or ai.get("text") or "").strip()
            lines.append(f"  - {owner} — {task}")
    else:
        lines.append("  (no action items from this meeting)")
    lines.append("")

    lines.append(f"OPEN TO-DOS HEADING INTO NEXT {cycle_word(cadence)}")
    if open_todos:
        for owner, items in _todos_grouped_by_owner(open_todos):
            lines.append(f"  {owner}")
            for t in items:
                task = (t.get("task") or "").strip()
                due = (t.get("due") or "").strip()
                tail = f" ({due})" if due else ""
                lines.append(f"    - {task}{tail}")
    else:
        lines.append("  (no open to-dos)")
    lines.append("")

    portal_link = f"{portal_url.rstrip('/')}/meetings/{meeting.get('id', '')}"
    lines.append(f"Full portal view: {portal_link}")
    lines.append("")
    lines.append("— Chris")

    return "\n".join(lines)


def render_email(meeting: dict[str, Any], open_todos: list[dict[str, Any]],
                 *, subject_prefix: str, portal_name: str, portal_url: str,
                 cadence: str) -> tuple[str, str, str]:
    """Top-level: returns (subject, html_body, text_body)."""
    subject = render_subject(subject_prefix, meeting)
    html = render_html(meeting, open_todos, portal_name, portal_url, cadence)
    text = render_text(meeting, open_todos, portal_name, portal_url, cadence)
    return subject, html, text
