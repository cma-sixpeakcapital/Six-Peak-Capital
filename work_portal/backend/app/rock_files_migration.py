"""One-time migration: pull URLs out of rock text into the ``files`` list.

People pasted raw Dropbox URLs into rock ``notes`` / ``done_definition`` (and,
historically, the singular ``link`` field). This transform lifts each URL into a
proper ``files[]`` entry with a derived/contextual label and strips it from the
prose, tidying the leftover whitespace and any now-orphaned label line (e.g.
``FINAL MATERIALS:``).

Pure and DB-free so it unit-tests without Postgres. ``scripts/migrate_rock_files``
wires it to the live ``rocks_doc`` with dry-run / snapshot / rollback.

Design:
  * ``build_plan(data)``  -> list of per-rock changes, mutating NOTHING.
  * ``apply_plan(data, plan)`` -> mutates ``data`` in place, returns a rollback
    manifest (original field text + the file ids it created).
  * ``rollback(data, manifest)`` -> restores text, removes those file ids.

Idempotent: after a run the text holds no URLs, so a second ``build_plan`` yields
an empty plan. Dedup is by normalized URL per rock (and against files already
present), so a URL sitting in both text and ``files`` won't double up.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urlparse

from .rock_files import build_file_entry, derive_label
from .storage import iter_all_rocks

# Fields whose free text we scan for URLs.
TEXT_FIELDS = ("notes", "done_definition")

_URL_RE = re.compile(r"https?://[^\s<>\"'\)\]]+")
_TRAILING_PUNCT = ".,;:!?"
# A wrapped-URL continuation: a line that starts like a query/path fragment
# (?rlkey=…, &dl=0, /more/path) or a bare key=value — i.e. a soft-wrapped URL
# tail, not prose.
_CONT = r"(?:[?&/]|[A-Za-z0-9_]+=)[^\s]*"
_STITCH_RE = re.compile(r"(https?://\S+)\r?\n[ \t]*(" + _CONT + r")")


def _stitch_wrapped(text: str) -> str:
    """Re-join a URL that got hard-wrapped across a newline.

    ``https://…/\nrlkey=…&dl=0`` -> ``https://…/rlkey=…&dl=0``. Runs to a fixed
    point so a URL split across several lines is fully rejoined.
    """
    prev = None
    while prev != text:
        prev = text
        text = _STITCH_RE.sub(r"\1\2", text)
    return text


def _strip_trailing_punct(url: str) -> str:
    while url and url[-1] in _TRAILING_PUNCT:
        url = url[:-1]
    return url


def normalize_url(url: str) -> tuple[str, str, str, str]:
    """Dedup key: scheme+host lowercased, path minus trailing slash, query kept.

    Query is significant (Dropbox ``rlkey`` differs per link), so it stays in
    the key. Never used to rewrite the stored URL — only to compare.
    """
    parsed = urlparse((url or "").strip())
    return (
        parsed.scheme.lower(),
        parsed.netloc.lower(),
        parsed.path.rstrip("/"),
        parsed.query,
    )


def _is_label_line(line: str) -> bool:
    """A short line that reads as a heading for the URL beneath it.

    Colon-terminated (``FINAL MATERIALS:``) or ALL-CAPS, up to ~80 chars.
    """
    s = line.strip()
    if not s or len(s) > 80:
        return False
    if s.endswith(":"):
        return True
    letters = [c for c in s if c.isalpha()]
    return bool(letters) and s.upper() == s


def _label_from_line(line: str) -> str:
    return line.strip().rstrip(":").strip()


def _split_trailing_label(prefix: str) -> tuple[str, str | None]:
    """Split same-line text before a URL into (kept_prose, label|None).

    Handles the inline case ``"...sentence. HERE IS THE LINK:  <url>"`` — the
    trailing colon/ALL-CAPS clause becomes the label and the earlier prose is
    kept. Falls back to using the whole prefix as the label when it is itself a
    short heading, else keeps the whole prefix as prose with no label.
    """
    s = (prefix or "").strip()
    if not s:
        return "", None
    breaks = list(re.finditer(r"[.!?]\s+", s))
    if breaks:
        cut = breaks[-1].end()
        earlier, trailing = s[:cut].strip(), s[cut:].strip()
    else:
        earlier, trailing = "", s
    if trailing and _is_label_line(trailing):
        return earlier, _label_from_line(trailing)
    if _is_label_line(s):
        return "", _label_from_line(s)
    return s, None


def migrate_text(text: str | None) -> tuple[str, list[tuple[str, str | None]]]:
    """Return (cleaned_text, [(url, label_hint), …]).

    ``label_hint`` is a context label (from a colon/ALL-CAPS line) or None to
    signal "derive from the URL". Leaves ``text`` untouched (returns it as-is)
    when it holds no URL, which is what makes the migration idempotent.
    """
    if not text or not text.strip():
        return text, []
    stitched = _stitch_wrapped(text)
    if not _URL_RE.search(stitched):
        return text, []

    out_lines: list[str] = []
    found: list[tuple[str, str | None]] = []

    for raw_line in stitched.split("\n"):
        matches = list(_URL_RE.finditer(raw_line))
        if not matches:
            out_lines.append(raw_line)
            continue

        first = matches[0]
        prefix = raw_line[: first.start()]

        # Determine the label: prefer a trailing colon/CAPS clause on this line,
        # else a heading line immediately above, else derive from the URL.
        kept_prose, label = _split_trailing_label(prefix)
        if label is None:
            back = len(out_lines) - 1
            while back >= 0 and not out_lines[back].strip():
                back -= 1
            if back >= 0 and _is_label_line(out_lines[back]) and not _URL_RE.search(out_lines[back]):
                label = _label_from_line(out_lines[back])
                del out_lines[back]  # orphan-removal: the heading had only this URL

        for i, m in enumerate(matches):
            url = _strip_trailing_punct(m.group(0))
            if not url:
                continue
            found.append((url, label if i == 0 else None))

        # Rebuild the leftover text: kept prose before the label/URL, plus any
        # text after the URL(s), with the URLs themselves removed.
        tail = _URL_RE.sub(" ", raw_line[first.start():])
        remainder = re.sub(r"\s{2,}", " ", (kept_prose + " " + tail)).strip()
        remainder = remainder.strip("?& \t").strip()
        if remainder:
            out_lines.append(remainder)

    cleaned = "\n".join(out_lines)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)      # trailing spaces per line
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)      # collapse blank runs
    cleaned = cleaned.strip()
    return cleaned, found


def _link_field_url(rock: dict[str, Any]) -> str | None:
    """The legacy singular ``link`` value, only if it is an http(s) URL."""
    link = (rock.get("link") or "").strip()
    if not link:
        return None
    parsed = urlparse(link)
    if parsed.scheme in ("http", "https") and parsed.netloc:
        return link
    return None


def _owner_for(rock: dict[str, Any], individual_owner: str | None) -> str | None:
    return individual_owner or rock.get("owner") or None


def build_plan(
    data: dict[str, Any],
    *,
    now: datetime | None = None,
    id_factory: Callable[[], str] = lambda: uuid.uuid4().hex,
) -> list[dict[str, Any]]:
    """Compute per-rock changes without mutating ``data``.

    Each change: ``{rock_id, owner, title, fields:{name:{before,after}},
    new_files:[entry,…]}``. Only rocks that actually change are included.
    """
    now = now or datetime.now(timezone.utc)

    # Map each rock id to its individual owner (company rocks: None here).
    owner_by_id: dict[str, str] = {}
    for owner, rocks in (data.get("rocks") or {}).items():
        for r in rocks:
            if r.get("id"):
                owner_by_id[r["id"]] = owner

    plan: list[dict[str, Any]] = []
    for rock in iter_all_rocks(data):
        rock_id = rock.get("id")
        if not rock_id:
            continue
        owner = _owner_for(rock, owner_by_id.get(rock_id))

        # Seen-URL set: dedup against files already on the rock, then within run.
        seen: set[tuple[str, str, str, str]] = set()
        for existing in rock.get("files") or []:
            seen.add(normalize_url(existing.get("url", "")))

        field_changes: dict[str, dict[str, str]] = {}
        collected: list[tuple[str, str | None, str | None]] = []  # (url, label, added_by)

        for field in TEXT_FIELDS:
            before = rock.get(field)
            cleaned, urls = migrate_text(before)
            if urls and cleaned != (before or ""):
                field_changes[field] = {"before": before or "", "after": cleaned}
            for url, label in urls:
                collected.append((url, label, owner))

        # Legacy singular link (URL-valued only). Clear the field, keep entry.
        link_url = _link_field_url(rock)
        if link_url:
            field_changes["link"] = {"before": rock.get("link", ""), "after": ""}
            collected.append((link_url, None, owner))

        # De-dup and build file entries in encounter order.
        new_files: list[dict[str, Any]] = []
        for url, label, added_by in collected:
            key = normalize_url(url)
            if key in seen:
                continue
            seen.add(key)
            entry = build_file_entry(
                url, label, added_by, now=now, id_factory=id_factory,
            )
            new_files.append(entry)

        if new_files or field_changes:
            plan.append({
                "rock_id": rock_id,
                "owner": owner or "Company",
                "title": rock.get("title", ""),
                "fields": field_changes,
                "new_files": new_files,
            })

    return plan


def apply_plan(data: dict[str, Any], plan: list[dict[str, Any]], run_id: str) -> dict[str, Any]:
    """Mutate ``data`` per ``plan``; return a rollback manifest.

    Manifest: ``{run_id, changes:[{rock_id, fields:{name:before}, added_file_ids}]}``.
    """
    by_id = {r.get("id"): r for r in iter_all_rocks(data)}
    manifest_changes: list[dict[str, Any]] = []
    for change in plan:
        rock = by_id.get(change["rock_id"])
        if rock is None:
            continue
        before_fields: dict[str, str] = {}
        for field, edit in change["fields"].items():
            before_fields[field] = rock.get(field, "")
            rock[field] = edit["after"]
        files = rock.get("files") or []
        files.extend(change["new_files"])
        rock["files"] = files
        manifest_changes.append({
            "rock_id": change["rock_id"],
            "fields": before_fields,
            "added_file_ids": [f["id"] for f in change["new_files"]],
        })
    return {"run_id": run_id, "changes": manifest_changes}


def rollback(data: dict[str, Any], manifest: dict[str, Any]) -> int:
    """Undo an applied run: restore field text, remove the files it created.

    Returns the number of rocks touched.
    """
    by_id = {r.get("id"): r for r in iter_all_rocks(data)}
    touched = 0
    for change in manifest.get("changes", []):
        rock = by_id.get(change["rock_id"])
        if rock is None:
            continue
        for field, before in change.get("fields", {}).items():
            rock[field] = before
        remove_ids = set(change.get("added_file_ids", []))
        if remove_ids:
            rock["files"] = [
                f for f in (rock.get("files") or []) if f.get("id") not in remove_ids
            ]
        touched += 1
    return touched


def format_plan(plan: list[dict[str, Any]]) -> str:
    """Human-readable before/after diff for the dry-run output."""
    if not plan:
        return "(no rocks have URLs in their text — nothing to migrate)"
    lines: list[str] = []
    total_files = 0
    for change in plan:
        lines.append(f"\n* [{change['owner']}] {change['title']!r}  ({change['rock_id']})")
        for field, edit in change["fields"].items():
            lines.append(f"    {field}:")
            lines.append(f"      - before: {edit['before']!r}")
            lines.append(f"      + after:  {edit['after']!r}")
        for f in change["new_files"]:
            total_files += 1
            lines.append(f"    + file: label={f['label']!r}  url={f['url']!r}")
    lines.append(
        f"\nSUMMARY: {len(plan)} rock(s) changed, {total_files} file link(s) extracted."
    )
    return "\n".join(lines)
