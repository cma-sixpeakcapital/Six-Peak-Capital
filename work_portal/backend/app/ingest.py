"""Ingestion pipeline: webhook payload or Read.ai pull -> storage."""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .readai import ReadAIClient, _normalize
from .storage import Storage
from .summarizer import Summarizer


@dataclass
class IngestService:
    storage: Storage
    summarizer: Summarizer
    readai: ReadAIClient | None = None

    def ingest_webhook(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Accept a Read.ai webhook payload (one meeting) and persist it."""
        meeting = payload.get("meeting") or payload
        normalized = _normalize(meeting)
        return self._finalize(normalized)

    def refresh_from_readai(self) -> list[dict[str, Any]]:
        """Pull meetings from Read.ai and persist any that are new."""
        if self.readai is None:
            raise RuntimeError("Read.ai client not configured")
        meetings = self.readai.list_recent_meetings()
        saved: list[dict[str, Any]] = []
        for m in meetings:
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
        meeting.setdefault("ingested_at", datetime.now(timezone.utc).isoformat())
        if not meeting.get("id"):
            meeting["id"] = meeting.get("date") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%S")
        self.storage.save_meeting(meeting)
        return meeting
