from types import SimpleNamespace

from app.summarizer import Summarizer, _extract_tool_input


def _fake_response(data: dict) -> SimpleNamespace:
    return SimpleNamespace(
        content=[SimpleNamespace(type="tool_use", input=data)]
    )


class _FakeMessages:
    def __init__(self, response):
        self.response = response
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class _FakeAnthropic:
    def __init__(self, response):
        self.messages = _FakeMessages(response)


def test_extract_tool_input_from_object() -> None:
    resp = _fake_response({"summary": "s", "action_items": [{"owner": "Chris", "task": "t"}], "files": []})
    out = _extract_tool_input(resp)
    assert out["summary"] == "s"
    assert out["action_items"][0]["owner"] == "Chris"


def test_extract_tool_input_from_dict_block() -> None:
    resp = SimpleNamespace(content=[{"type": "tool_use", "input": {"summary": "x", "action_items": [], "files": []}}])
    assert _extract_tool_input(resp)["summary"] == "x"


def test_extract_tool_input_empty_when_missing() -> None:
    resp = SimpleNamespace(content=[SimpleNamespace(type="text", text="hi")])
    assert _extract_tool_input(resp) == {"summary": "", "action_items": [], "files": []}


def test_summarize_empty_transcript_short_circuits() -> None:
    s = Summarizer(api_key="fake", client=_FakeAnthropic(_fake_response({"summary": "nope"})))
    out = s.summarize("   ")
    assert out == {"summary": "", "action_items": [], "files": []}
    assert s.client.messages.calls == []


def test_summarize_calls_anthropic_with_caching_and_tool() -> None:
    payload = {
        "summary": "Acama GMP approved.",
        "action_items": [{"owner": "Chris", "task": "Send docs", "due": "2026-04-21"}],
        "files": [{"name": "GMP.xlsx", "note": "for lender"}],
    }
    fake = _FakeAnthropic(_fake_response(payload))
    s = Summarizer(api_key="fake", client=fake, model="claude-haiku-4-5-20251001")
    out = s.summarize("A real transcript", title="L10 Apr 14")
    assert out == payload
    call = fake.messages.calls[0]
    assert call["model"] == "claude-haiku-4-5-20251001"
    assert call["tool_choice"]["name"] == "record_l10_summary"
    assert call["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "L10 Apr 14" in call["messages"][0]["content"]
