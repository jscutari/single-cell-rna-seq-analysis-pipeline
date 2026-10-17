"""agents/llm.py: request shape, response parsing, and the llm_call event."""

from types import SimpleNamespace

import pytest
from openai.types.chat import ChatCompletion
from pydantic import BaseModel

from agents import llm


def completion(content="answer", reasoning_field="reasoning", reasoning="thinking...", tool_calls=None,
               usage=(12, 34)) -> ChatCompletion:
    message = {"role": "assistant", "content": content, "tool_calls": tool_calls}
    if reasoning_field:
        message[reasoning_field] = reasoning
    data = {"id": "x", "object": "chat.completion", "created": 0, "model": "lightning",
            "choices": [{"index": 0, "finish_reason": "stop", "message": message}]}
    if usage:
        data["usage"] = {"prompt_tokens": usage[0], "completion_tokens": usage[1],
                         "total_tokens": sum(usage)}
    return ChatCompletion.model_validate(data)


@pytest.fixture
def client(monkeypatch):
    sent: list[dict] = []
    box = {"response": completion()}

    async def create(**kwargs):
        sent.append(kwargs)
        return box["response"]

    monkeypatch.setattr(llm, "_client", SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    return SimpleNamespace(sent=sent, box=box)


async def test_returns_llm_call_and_emits_it(client, events):
    call = await llm.chat("coder", [{"role": "user", "content": "hi"}], project_id="p", hypothesis_id="h",
                          parent_call_id="parent")
    assert call.output == "answer" and call.reasoning == "thinking..."
    assert (call.tokens_in, call.tokens_out) == (12, 34)
    assert call.agent == "coder" and call.hypothesis_id == "h" and call.parent_call_id == "parent"
    assert call.latency_ms >= 0
    assert [e.type for e in events] == ["llm_call"] and events[0].payload["id"] == call.id


async def test_reasoning_toggle_is_sent_through_the_chat_template(client, events):
    await llm.chat("a", [], project_id="p", reasoning=False)
    await llm.chat("a", [], project_id="p")
    assert client.sent[0]["extra_body"]["chat_template_kwargs"] == {"enable_thinking": False}
    assert client.sent[1]["extra_body"]["chat_template_kwargs"] == {"enable_thinking": True}
    assert client.sent[0]["model"] == llm.MODEL


async def test_older_reasoning_content_field_is_read_too(client, events):
    client.box["response"] = completion(reasoning_field="reasoning_content", reasoning="old field")
    assert (await llm.chat("a", [], project_id="p")).reasoning == "old field"


async def test_no_reasoning_and_no_usage(client, events):
    client.box["response"] = completion(reasoning_field=None, usage=None, content=None)
    call = await llm.chat("a", [], project_id="p", reasoning=False)
    assert call.reasoning is None and call.output == "" and call.tokens_in == 0


async def test_schema_becomes_a_json_schema_response_format(client, events):
    class Answer(BaseModel):
        verdict: str

    await llm.chat("critic", [], project_id="p", schema=Answer)
    rf = client.sent[0]["response_format"]
    assert rf["type"] == "json_schema" and rf["json_schema"]["name"] == "Answer"
    assert rf["json_schema"]["schema"]["required"] == ["verdict"]


async def test_tools_add_force_nonempty_content_and_tool_calls_are_recorded(client, events):
    tool_calls = [{"id": "t1", "type": "function", "function": {"name": "f", "arguments": "{}"}}]
    client.box["response"] = completion(tool_calls=tool_calls)
    tools = [{"type": "function", "function": {"name": "f", "parameters": {}}}]
    call = await llm.chat("a", [], project_id="p", tools=tools)
    assert client.sent[0]["tools"] == tools
    assert client.sent[0]["extra_body"]["chat_template_kwargs"]["force_nonempty_content"] is True
    assert call.tool_calls[0]["function"]["name"] == "f"


async def test_no_tools_or_schema_sends_neither(client, events):
    await llm.chat("a", [], project_id="p")
    assert "tools" not in client.sent[0] and "response_format" not in client.sent[0]
