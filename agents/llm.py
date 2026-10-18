"""vLLM client; logs every call as an LLMCall event.

Every agent talks to the model through chat(), so every call shows up in the
Trace tab with its prompt, reasoning, answer, tokens and latency.

Smoke test (vLLM must be running):  uv run python -m agents.llm
"""

import asyncio
import logging
import os
import time
import weakref
from typing import Any, TypeVar

from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from shared.events import Event, EventType, emit
from shared.schemas import LLMCall

VLLM_URL = os.environ.get("VLLM_URL", "http://localhost:8000/v1")
MODEL = os.environ.get("VLLM_MODEL", "lightning")
# Structured (JSON) replies: retries, and a lower token cap so a runaway reply ends sooner.
JSON_ATTEMPTS = 3
JSON_MAX_TOKENS = 12000  # reasoning counts toward this; vLLM blocks whitespace runaways
log = logging.getLogger("scrap.llm")
T = TypeVar("T", bound=BaseModel)


class StructuredOutputError(RuntimeError):
    """The model never produced valid JSON for the schema."""

# One client per event loop: a client's pooled connections belong to the loop that
# opened them, and reusing them from another loop fails with "Event loop is closed".
_clients: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, AsyncOpenAI]" = weakref.WeakKeyDictionary()


def _get_client() -> AsyncOpenAI:
    loop = asyncio.get_running_loop()
    if loop not in _clients:
        # vLLM doesn't check the key, but the client requires one.
        _clients[loop] = AsyncOpenAI(base_url=VLLM_URL, api_key="unused", timeout=600)
    return _clients[loop]


async def chat(
    agent: str,
    messages: list[dict[str, Any]],
    *,
    project_id: str,
    hypothesis_id: str | None = None,
    reasoning: bool = True,
    tools: list[dict[str, Any]] | None = None,
    parent_call_id: str | None = None,
    schema: type[BaseModel] | None = None,
    max_tokens: int = 16000,
    temperature: float = 1.0,
    top_p: float = 0.95,
) -> LLMCall:
    """One model call. Returns the LLMCall (answer in .output) and emits it as an event.

    With `schema`, vLLM constrains the answer (after any reasoning) to JSON matching
    that Pydantic model; parse it with schema.model_validate_json(call.output).
    """
    # Per the model card: reasoning is switched per request through the chat template.
    template_kwargs: dict[str, Any] = {"enable_thinking": reasoning}
    extra: dict[str, Any] = {}
    if tools:
        template_kwargs["force_nonempty_content"] = True
        extra["tools"] = tools
    if schema:
        extra["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": schema.__name__, "schema": schema.model_json_schema()},
        }

    start = time.perf_counter()
    resp = await _get_client().chat.completions.create(
        model=MODEL,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=top_p,
        extra_body={"chat_template_kwargs": template_kwargs},
        **extra,
    )
    latency_ms = int((time.perf_counter() - start) * 1000)

    msg = resp.choices[0].message
    # The reasoning parser puts the model's thinking in a non-standard field;
    # vLLM has used both names across versions.
    fields = msg.model_extra or {}
    reasoning_text = fields.get("reasoning") or fields.get("reasoning_content")

    call = LLMCall(
        project_id=project_id,
        hypothesis_id=hypothesis_id,
        agent=agent,
        messages=messages,
        reasoning=reasoning_text,
        output=msg.content or "",
        tool_calls=[tc.model_dump() for tc in msg.tool_calls or []],
        tokens_in=resp.usage.prompt_tokens if resp.usage else 0,
        tokens_out=resp.usage.completion_tokens if resp.usage else 0,
        latency_ms=latency_ms,
        parent_call_id=parent_call_id,
    )
    emit(Event(type=EventType.llm_call, project_id=project_id, payload=call))
    return call


async def chat_json(agent: str, messages: list[dict[str, Any]], schema: type[T], *,
                    attempts: int = JSON_ATTEMPTS, chat_fn=None, **kwargs: Any) -> tuple[LLMCall, T]:
    """chat() with a JSON schema, parsed and validated; retries when the reply is unusable.

    Schema-constrained decoding still allows whitespace, and the model sometimes gets
    stuck emitting it until the token limit, leaving truncated JSON. That is rare and
    random, so asking again almost always works. Each attempt is its own llm_call event,
    linked to the failed one through parent_call_id. chat_fn defaults to chat(); callers
    pass their module's own `chat` so tests can substitute a fake model.
    """
    chat_fn = chat_fn or chat
    kwargs.setdefault("max_tokens", JSON_MAX_TOKENS)
    parent = kwargs.pop("parent_call_id", None)
    for attempt in range(1, attempts + 1):
        call = await chat_fn(agent, messages, schema=schema, parent_call_id=parent, **kwargs)
        try:
            return call, schema.model_validate_json(call.output)
        except ValidationError as error:
            log.warning("%s: invalid %s JSON (attempt %d/%d, %d tokens): %s", agent, schema.__name__,
                        attempt, attempts, call.tokens_out, str(error).splitlines()[0])
            parent = call.id
    raise StructuredOutputError(f"{agent}: no valid {schema.__name__} after {attempts} attempts")


async def _smoke_test(n: int = 10) -> None:
    """Fire n calls at once; vLLM should batch them, so total time ≈ the slowest call, not the sum."""
    questions = [f"In one sentence, what does gene {g} do?" for g in
                 ["IFI27", "ISG15", "HLA-DRA", "CD14", "FCGR3A", "MS4A1", "CD8A", "NKG7", "PPBP", "S100A8"]]
    start = time.perf_counter()
    calls = await asyncio.gather(*(
        chat("smoke_test", [{"role": "user", "content": q}], project_id="smoke", reasoning=(i % 2 == 0))
        for i, q in enumerate(questions[:n])
    ))
    wall = time.perf_counter() - start
    print("\n--- summary ---")
    for c in calls:
        print(f"{c.latency_ms:>6} ms  {c.tokens_out:>5} tok  reasoning={'yes' if c.reasoning else 'no ':3}  {c.output[:70]!r}")
    total_out = sum(c.tokens_out for c in calls)
    print(f"{n} calls in {wall:.1f}s wall, sum of latencies {sum(c.latency_ms for c in calls) / 1000:.1f}s, "
          f"{total_out / wall:.0f} output tok/s overall")


if __name__ == "__main__":
    asyncio.run(_smoke_test())
