from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

import requests


class HttpClient(Protocol):
    def get(self, url: str, headers: dict[str, str], params: dict[str, Any]) -> "HttpResponse":
        ...


class HttpResponse(Protocol):
    status_code: int

    def json(self) -> Any: ...


class _RequestsClient:
    def get(self, url: str, headers: dict[str, str], params: dict[str, Any]) -> Any:
        return requests.get(url, headers=headers, params=params, timeout=30)


@dataclass
class ReadAIClient:
    api_key: str
    base_url: str = "https://api.read.ai/v1"
    http: HttpClient | None = None

    def _client(self) -> HttpClient:
        return self.http or _RequestsClient()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }

    def list_recent_meetings(self, since: datetime | None = None, tag: str | None = "L10") -> list[dict[str, Any]]:
        """Pull meetings from Read.ai since the given datetime.

        Returns a normalized list of meeting dicts with keys:
        id, title, date, attendees, transcript, summary, action_items, files.
        Missing fields default to empty. Caller should enrich via summarizer
        if summary/action_items/files are absent.
        """
        if not self.api_key:
            raise RuntimeError("READAI_API_KEY not configured")
        since = since or datetime.now(timezone.utc) - timedelta(days=7)
        params: dict[str, Any] = {"since": since.isoformat()}
        if tag:
            params["tag"] = tag
        resp = self._client().get(f"{self.base_url}/meetings", headers=self._headers(), params=params)
        if resp.status_code >= 400:
            raise RuntimeError(f"Read.ai API error: {resp.status_code}")
        payload = resp.json()
        if isinstance(payload, list):
            raw = payload
        elif isinstance(payload, dict):
            raw = payload.get("meetings", [])
        else:
            raw = []
        return [_normalize(m) for m in raw]


def _normalize(raw: dict[str, Any]) -> dict[str, Any]:
    date_str = raw.get("date") or raw.get("start_time") or raw.get("started_at") or ""
    if date_str and "T" in date_str:
        date_str = date_str.split("T", 1)[0]
    attendees = raw.get("attendees") or raw.get("participants") or []
    if attendees and isinstance(attendees[0], dict):
        attendees = [a.get("name") or a.get("email") or "" for a in attendees]
    return {
        "id": str(raw.get("id") or raw.get("meeting_id") or date_str),
        "title": raw.get("title") or raw.get("name") or "L10 Meeting",
        "date": date_str,
        "attendees": [a for a in attendees if a],
        "transcript": raw.get("transcript") or raw.get("transcript_text") or "",
        "summary": raw.get("summary") or "",
        "action_items": raw.get("action_items") or [],
        "files": raw.get("files") or raw.get("attachments") or [],
        "source_url": raw.get("url") or raw.get("share_url") or "",
    }
