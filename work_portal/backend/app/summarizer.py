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
