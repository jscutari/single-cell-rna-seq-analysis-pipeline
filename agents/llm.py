"""vLLM client; logs every call as an LLMCall event.

Every agent talks to the model through chat(), so every call shows up in the
Trace tab with its prompt, reasoning, answer, tokens and latency.

Smoke test (vLLM must be running):  uv run python -m agents.llm
"""

import asyncio
import os
import time
from typing import Any

from openai import AsyncOpenAI

from shared.events import Event, EventType, emit
from shared.schemas import LLMCall

VLLM_URL = os.environ.get("VLLM_URL", "http://localhost:8000/v1")
MODEL = os.environ.get("VLLM_MODEL", "lightning")

# vLLM doesn't check the key, but the client requires one.
_client = AsyncOpenAI(base_url=VLLM_URL, api_key="unused", timeout=600)


async def chat(
    agent: str,
    messages: list[dict[str, Any]],
    *,
    project_id: str,
    hypothesis_id: str | None = None,
    reasoning: bool = True,
    tools: list[dict[str, Any]] | None = None,
    parent_call_id: str | None = None,
    max_tokens: int = 16000,
    temperature: float = 1.0,
    top_p: float = 0.95,
) -> LLMCall:
    """One model call. Returns the LLMCall (answer in .output) and emits it as an event."""
    # Per the model card: reasoning is switched per request through the chat template.
    template_kwargs: dict[str, Any] = {"enable_thinking": reasoning}
    extra: dict[str, Any] = {}
    if tools:
        template_kwargs["force_nonempty_content"] = True
        extra["tools"] = tools

    start = time.perf_counter()
    resp = await _client.chat.completions.create(
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
