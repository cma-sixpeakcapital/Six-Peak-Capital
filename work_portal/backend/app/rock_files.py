"""Per-rock file links ("Files" section).

A rock can carry a ``files`` list — labeled links (Dropbox is the norm, but any
http(s) URL works). Each entry:

    {
      "id":       uuid4().hex,          # stable per entry (edit/remove target it)
      "label":    "PM Proposals",       # <= 60 chars, escaped on render
      "url":      "https://...",         # stored VERBATIM — query string intact
      "added_by": "Chris Aiello" | None,
      "added_at": "2026-08-04T13:22:05+00:00",
    }

This module holds the pure, DB-free pieces: URL/label validation, label
derivation, an autoescape-safe linkifier for bare URLs left in text, and the
single-rock mutation helpers both Storage backends call. The Storage classes own
load/save; these helpers own the rules so the two backends stay in parity.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urlparse, unquote

from markupsafe import Markup, escape

MAX_FILES_PER_ROCK = 10
LABEL_MAX = 60

# A bare URL run: http(s):// up to the first whitespace or markup-ish delimiter.
# Trailing sentence punctuation is trimmed separately so "see https://x.com."
# doesn't swallow the period into the href.
_URL_RE = re.compile(r"https?://[^\s<>\"'\)\]]+")
_TRAILING_PUNCT = ".,;:!?"


class FileValidationError(ValueError):
    """Raised for a bad url/label — surfaced as HTTP 400."""


class FileArchivedError(Exception):
    """Raised when a write targets an archived rock — surfaced as HTTP 403."""


def _host_label(parsed: Any) -> str:
    host = (parsed.netloc or "").split("@")[-1]  # drop any user-info
    if host.startswith("www."):
        host = host[4:]
    return host or "link"


def derive_label(url: str) -> str:
    """Derive a human label when none is given. Never returns the raw URL.

    Dropbox ``/scl/fo/`` folder → "Dropbox folder"; ``/scl/fi/`` file or a path
    ending in a filename → that filename; otherwise the hostname.
    """
    parsed = urlparse((url or "").strip())
    path = parsed.path or ""
    segments = [s for s in path.split("/") if s]

    if "/scl/fo/" in path:
        return "Dropbox folder"

    if "/scl/fi/" in path:
        # Dropbox file link: /scl/fi/<id>/<filename> — filename is the last seg.
        if segments and "." in segments[-1]:
            return unquote(segments[-1])
        return _host_label(parsed)

    # Generic: a trailing path segment that looks like a filename.
    if segments and "." in segments[-1]:
        return unquote(segments[-1])

    return _host_label(parsed)


def validate_url(url: str) -> str:
    """Trim, require a non-empty http(s) absolute URL, return it VERBATIM.

    Rejects ``javascript:``/``data:``/relative URLs. Never rewrites or strips the
    query string — Dropbox ``rlkey``/``dl`` params are load-bearing.
    """
    url = (url or "").strip()
    if not url:
        raise FileValidationError("url is required")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise FileValidationError("url must be an absolute http(s) link")
    return url


def clean_label(label: str | None, url: str) -> str:
    """Trim label; derive from url if blank; cap at LABEL_MAX chars."""
    label = (label or "").strip()
    if not label:
        label = derive_label(url)
    return label[:LABEL_MAX]


def build_file_entry(
    url: str,
    label: str | None = None,
    added_by: str | None = None,
    *,
    now: datetime | None = None,
    id_factory: Callable[[], str] = lambda: uuid.uuid4().hex,
) -> dict[str, Any]:
    """Validate and build a files[] entry. Raises FileValidationError on bad url."""
    clean_url = validate_url(url)
    now = now or datetime.now(timezone.utc)
    return {
        "id": id_factory(),
        "label": clean_label(label, clean_url),
        "url": clean_url,
        "added_by": added_by or None,
        "added_at": now.isoformat(),
    }


# --- bare-URL linkifier (render-time safety net) -------------------------------

def linkify(text: str | None, max_len: int = 40) -> Markup:
    """Escape ``text`` and turn bare http(s) URLs into truncated anchors.

    Returns a ``Markup`` (safe) string. All non-URL text is HTML-escaped; the
    href is escaped too. Anchor text is the URL truncated to ``max_len`` chars
    with an ellipsis, so a pasted URL can never blow out the card again.
    """
    if not text:
        return Markup("")
    parts: list[Any] = []
    last = 0
    for match in _URL_RE.finditer(text):
        url = match.group(0)
        # Trim trailing sentence punctuation back into the plain-text stream.
        while url and url[-1] in _TRAILING_PUNCT:
            url = url[:-1]
        if not url:
            continue
        start = match.start()
        parts.append(escape(text[last:start]))
        shown = url if len(url) <= max_len else url[: max_len - 1] + "…"
        parts.append(
            Markup(
                '<a href="{}" target="_blank" rel="noopener noreferrer"'
                ' class="rock-inline-link">{}</a>'
            ).format(url, shown)
        )
        last = start + len(url)
    parts.append(escape(text[last:]))
    return Markup("").join(parts)


# --- single-rock mutation helpers (called by both Storage backends) ------------

def apply_add_file(
    rock: dict[str, Any],
    url: str,
    label: str | None = None,
    added_by: str | None = None,
    **build_kwargs: Any,
) -> dict[str, Any]:
    """Append a validated entry to ``rock['files']``. Raises on cap/validation."""
    files = rock.get("files") or []
    if len(files) >= MAX_FILES_PER_ROCK:
        raise FileValidationError(
            f"a rock can hold at most {MAX_FILES_PER_ROCK} file links"
        )
    entry = build_file_entry(url, label, added_by, **build_kwargs)
    files.append(entry)
    rock["files"] = files
    return entry


def apply_update_file(
    rock: dict[str, Any],
    file_id: str,
    url: str | None = None,
    label: str | None = None,
) -> dict[str, Any] | None:
    """Patch an entry's url and/or label in place. Returns it, or None if absent.

    A url is only touched when ``url`` is provided (non-None); same for label.
    Passing label='' re-derives from the (new or existing) url.
    """
    for entry in rock.get("files") or []:
        if entry.get("id") == file_id:
            if url is not None:
                entry["url"] = validate_url(url)
            if label is not None:
                entry["label"] = clean_label(label, entry["url"])
            return entry
    return None


def apply_remove_file(rock: dict[str, Any], file_id: str) -> bool:
    """Drop the entry with ``file_id``. Returns True if one was removed."""
    files = rock.get("files") or []
    kept = [f for f in files if f.get("id") != file_id]
    if len(kept) == len(files):
        return False
    rock["files"] = kept
    return True
