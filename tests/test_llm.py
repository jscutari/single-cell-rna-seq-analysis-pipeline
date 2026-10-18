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

    fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(llm, "_get_client", lambda: fake)
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


async def test_each_event_loop_gets_its_own_client():
    import asyncio
    first = llm._get_client()
    assert llm._get_client() is first
    other = await asyncio.to_thread(lambda: asyncio.run(_client_in_new_loop()))
    assert other is not first


async def _client_in_new_loop():
    return llm._get_client()


async def test_no_tools_or_schema_sends_neither(client, events):
    await llm.chat("a", [], project_id="p")
    assert "tools" not in client.sent[0] and "response_format" not in client.sent[0]


# --- chat_json: structured replies with retries ---

class Verdict(BaseModel):
    verdict: str


def fake_chat(outputs):
    calls = []

    async def chat(agent, messages, **kwargs):
        from shared.schemas import LLMCall
        call = LLMCall(project_id="p", agent=agent, messages=messages, output=outputs[len(calls)],
                       parent_call_id=kwargs.get("parent_call_id"), tokens_out=7)
        calls.append({"kwargs": kwargs, "call": call})
        return call
    return chat, calls


async def test_chat_json_parses_valid_json():
    chat, calls = fake_chat(['{"verdict": "approve"}'])
    call, parsed = await llm.chat_json("critic", [], Verdict, chat_fn=chat, project_id="p")
    assert parsed.verdict == "approve" and len(calls) == 1
    assert calls[0]["kwargs"]["schema"] is Verdict and calls[0]["kwargs"]["max_tokens"] == llm.JSON_MAX_TOKENS


async def test_chat_json_retries_a_runaway_whitespace_reply():
    """Tonight's failure: thousands of blank lines, then the token limit cut the JSON off."""
    runaway = '{\n  "verdict": "app' + "\n  " * 3000
    chat, calls = fake_chat([runaway, '{"verdict": "approve"}'])
    call, parsed = await llm.chat_json("intake", [], Verdict, chat_fn=chat, project_id="p")
    assert parsed.verdict == "approve" and len(calls) == 2
    assert calls[1]["kwargs"]["parent_call_id"] == calls[0]["call"].id  # retry linked in the trace


async def test_chat_json_gives_up_after_the_last_attempt():
    chat, calls = fake_chat(["not json"] * 5)
    with pytest.raises(llm.StructuredOutputError, match="no valid Verdict after 3 attempts"):
        await llm.chat_json("critic", [], Verdict, chat_fn=chat, project_id="p")
    assert len(calls) == 3


async def test_chat_json_respects_explicit_max_tokens_and_parent():
    chat, calls = fake_chat(['{"verdict": "x"}'])
    await llm.chat_json("a", [], Verdict, chat_fn=chat, project_id="p", max_tokens=100, parent_call_id="root")
    assert calls[0]["kwargs"]["max_tokens"] == 100 and calls[0]["kwargs"]["parent_call_id"] == "root"
