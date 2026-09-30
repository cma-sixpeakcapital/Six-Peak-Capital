import json
from dataclasses import dataclass
from typing import Any, Protocol


SYSTEM_PROMPT = """You extract structured follow-up items from Level 10 (EOS) weekly \
leadership meeting transcripts.

Your job: read the transcript and produce a concise summary plus two structured lists:
action items and referenced files. Be faithful to the transcript — do not invent owners, \
deadlines, or file names that were not actually said. If a field is unknown, leave it empty.

Conventions:
- action_items.owner is the person assigned the task (first name is fine)
- action_items.due is an ISO date (YYYY-MM-DD) if a specific date was stated; otherwise ""
- files.name is the file or document referenced (e.g. "Acama_GMP.xlsx", "Q2 pipeline deck")
- files.note is a short phrase on why the team needs it (e.g. "needed for Thursday review")
- summary is 2-4 sentences, narrative — what was decided, what shifted, what's blocked
"""


TOOL_SCHEMA = {
    "name": "record_l10_summary",
    "description": "Record the structured summary of an L10 meeting transcript.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "2-4 sentence narrative summary of the meeting.",
            },
            "action_items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "owner": {"type": "string"},
                        "task": {"type": "string"},
                        "due": {"type": "string"},
                    },
                    "required": ["owner", "task"],
                },
            },
            "files": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "note": {"type": "string"},
                    },
                    "required": ["name"],
                },
            },
        },
        "required": ["summary", "action_items", "files"],
    },
}


TOPICS_PROMPT = """You organize a monthly LV Construction executive meeting summary by topic \
for Six Peak Capital, a Los Angeles real estate developer, and its general contractor, \
LV Construction.

Group the summary into the topics that were discussed, in the order they came up.
- 3 to 8 topics. Each topic title is 1-5 words and names the subject, e.g. \
"Staffing", "Active projects", "Bidding pipeline", "Off-site planning", "Reporting".
- Each topic has 1 to 5 notes. A note is one short factual line taken from the summary. \
Keep numbers, names and dates exactly. Never add facts that are not in the summary.
- Merge sentences that say the same thing. Drop filler such as "The meeting covered \
several topics" or an opening sentence that only lists the agenda.
- Every substantive fact in the summary must land under exactly one topic.
- Fix obvious speech-to-text misspellings of these known names when the intent is clear: \
LV Construction, Six Peak, Califa (not Galita), Whipple, Nelrose, Ramsgate, Crenshaw \
(not Fredshaw), Riverton, Riverton 75, Lexington, Acama, Francis, Troost (not Trust or Truce), \
Klump & Scott (not Clump or Columbus Scott), Reseda, Dickens, Moorpark, Kramerwood, HVN, MRK, \
Steyn (not Stein or Sting), Travelers, CBI, Box, Grady Lakamp, Pedro Rosales, Greg Smith, \
Dorian Puentes, Daniel Carrillo, Tom Taggart, Bob Kennedy, Chris Aiello, Chris Andresen, \
Derek Sanders, Schuyler Dietz. Otherwise keep the wording.
"""

TOPICS_TOOL = {
    "name": "record_topics",
    "description": "Record the meeting summary grouped by topic.",
    "input_schema": {
        "type": "object",
        "properties": {
            "topics": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "topic": {"type": "string"},
                        "notes": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["topic", "notes"],
                },
            },
        },
        "required": ["topics"],
    },
}


def clean_topics(raw: Any) -> list[dict[str, Any]]:
    """Keep only well-formed topics: a non-empty title and at least one note."""
    out: list[dict[str, Any]] = []
    for t in raw or []:
        if not isinstance(t, dict):
            continue
        title = str(t.get("topic") or "").strip()
        notes = [str(n).strip() for n in (t.get("notes") or []) if str(n).strip()]
        if title and notes:
            out.append({"topic": title, "notes": notes})
    return out


class AnthropicLike(Protocol):
    class messages:  # type: ignore[no-redef]
        @staticmethod
        def create(**kwargs: Any) -> Any: ...


@dataclass
class Summarizer:
    api_key: str
    model: str = "claude-haiku-4-5-20251001"
    client: Any | None = None

    def _get_client(self) -> Any:
        if self.client is not None:
            return self.client
        from anthropic import Anthropic
        self.client = Anthropic(api_key=self.api_key)
        return self.client

    def summarize(self, transcript: str, title: str = "L10 Meeting") -> dict[str, Any]:
        if not transcript.strip():
            return {"summary": "", "action_items": [], "files": []}
        client = self._get_client()
        response = client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            tools=[TOOL_SCHEMA],
            tool_choice={"type": "tool", "name": "record_l10_summary"},
            messages=[
                {
                    "role": "user",
                    "content": f"Meeting title: {title}\n\nTranscript:\n{transcript}",
                }
            ],
        )
        return _extract_tool_input(response)

    def group_topics(self, summary: str, title: str = "LV Exec Meeting") -> list[dict[str, Any]]:
        """Regroup a meeting summary (e.g. Read.ai's) into topics with notes."""
        if not (summary or "").strip():
            return []
        client = self._get_client()
        response = client.messages.create(
            model=self.model,
            max_tokens=2000,
            system=[{"type": "text", "text": TOPICS_PROMPT, "cache_control": {"type": "ephemeral"}}],
            tools=[TOPICS_TOOL],
            tool_choice={"type": "tool", "name": "record_topics"},
            messages=[{"role": "user", "content": f"Meeting title: {title}\n\nSummary:\n{summary}"}],
        )
        for block in getattr(response, "content", []) or []:
            btype = getattr(block, "type", None) or (block.get("type") if isinstance(block, dict) else None)
            if btype == "tool_use":
                data = getattr(block, "input", None)
                if data is None and isinstance(block, dict):
                    data = block.get("input")
                if isinstance(data, str):
                    data = json.loads(data)
                if isinstance(data, dict):
                    return clean_topics(data.get("topics"))
        return []


def _extract_tool_input(response: Any) -> dict[str, Any]:
    for block in getattr(response, "content", []) or []:
        block_type = getattr(block, "type", None) or (block.get("type") if isinstance(block, dict) else None)
        if block_type == "tool_use":
            data = getattr(block, "input", None)
            if data is None and isinstance(block, dict):
                data = block.get("input")
            if isinstance(data, str):
                data = json.loads(data)
            if isinstance(data, dict):
                return {
                    "summary": data.get("summary", ""),
                    "action_items": data.get("action_items", []) or [],
                    "files": data.get("files", []) or [],
                }
    return {"summary": "", "action_items": [], "files": []}
