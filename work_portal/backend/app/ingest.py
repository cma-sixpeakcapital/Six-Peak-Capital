"""Ingestion pipeline: webhook payload or Read.ai pull -> storage."""
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .readai import ReadAIClient, _normalize
from .storage import Storage
from .summarizer import Summarizer


# Match a leading subject phrase followed by an intent verb like
# "will / should / must / needs to / plans to / agreed to". Captures up to
# 80 chars before the verb so compound owners ("Schuyler Dietz & Chris Aiello",
# "Pedro Rosales, Greg Smith, and Grady Lakamp") survive intact.
_OWNER_RE = re.compile(
    r"^(.{2,80}?)\s+(?:will|should|must|needs\s+to|plans\s+to|agreed\s+to)\s+\w",
    re.IGNORECASE,
)


def _extract_owner(text: str) -> str:
    """Best-effort owner extraction from the start of a Read.ai action sentence.

    Returns the leading subject phrase or "" when no confident match.
    """
    if not text:
        return ""
    m = _OWNER_RE.match(text)
    if not m:
        return ""
    owner = m.group(1).strip().rstrip(",.;:")
    # Reject pronouns / generic subjects that aren't really owners
    if owner.lower() in {"it", "this", "that", "there", "they", "we", "you", "everyone", "the team"}:
        return ""
    # Require it to start capitalized — proper noun-ish
    if not owner or not owner[0].isupper():
        return ""
    return owner


def _assign_action_item_ids(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize action items at ingest time.

    Read.ai sends action items as ``{id, text, completed}`` (one sentence per
    item, owner baked in). Our internal shape is ``{id, owner, task, due,
    completed}``. Map ``text`` -> ``task`` and extract a likely owner from
    the start of the sentence so the rest of the app can rely on a stable
    schema.
    """
    out: list[dict[str, Any]] = []
    for item in items or []:
        item = dict(item)
        item.setdefault("id", f"ai_{uuid.uuid4().hex[:10]}")
        item.setdefault("completed", False)
        if not item.get("task") and item.get("text"):
            item["task"] = item["text"]
        if not item.get("owner"):
            owner = _extract_owner(item.get("task") or item.get("text") or "")
            if owner:
                item["owner"] = owner
        out.append(item)
    return out


@dataclass
class IngestService:
    storage: Storage
    summarizer: Summarizer
    readai: ReadAIClient | None = None
    title_pattern: str = ""

    def title_matches(self, title: str) -> bool:
        if not self.title_pattern:
            return True
        try:
            return bool(re.search(self.title_pattern, title or ""))
        except re.error:
            return True

    def ingest_webhook(self, payload: dict[str, Any]) -> dict[str, Any]:
        meeting = payload.get("meeting") or payload
        normalized = _normalize(meeting)
        if not self.title_matches(normalized.get("title", "")):
            return {"status": "ignored", "reason": "title_filter", "meeting": normalized}
        return self._finalize(normalized)

    def refresh_from_readai(self) -> list[dict[str, Any]]:
        if self.readai is None:
            raise RuntimeError("Read.ai client not configured")
        meetings = self.readai.list_recent_meetings()
        saved: list[dict[str, Any]] = []
        for m in meetings:
            if not self.title_matches(m.get("title", "")):
                continue
            if self.storage.get_meeting(m["id"]):
                continue
            saved.append(self._finalize(m))
        return saved

    def _finalize(self, meeting: dict[str, Any]) -> dict[str, Any]:
        needs_summary = not meeting.get("summary") or not meeting.get("action_items")
        if needs_summary and meeting.get("transcript"):
            extracted = self.summarizer.summarize(
                meeting["transcript"], title=meeting.get("title", "L10 Meeting")
            )
            meeting["summary"] = extracted.get("summary") or meeting.get("summary", "")
            if not meeting.get("action_items"):
                meeting["action_items"] = extracted.get("action_items", [])
            if not meeting.get("files"):
                meeting["files"] = extracted.get("files", [])
        meeting["action_items"] = _assign_action_item_ids(meeting.get("action_items") or [])
        meeting.setdefault("ingested_at", datetime.now(timezone.utc).isoformat())
        if not meeting.get("id"):
            meeting["id"] = meeting.get("date") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%S")
        self.storage.save_meeting(meeting)
        try:
            self.storage.purge_completed_todos()
        except AttributeError:
            pass
        return meeting
