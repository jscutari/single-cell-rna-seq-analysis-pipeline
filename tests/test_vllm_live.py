"""Real calls to vLLM on localhost:8000 (skipped when it isn't running)."""

import httpx
import pytest
from pydantic import BaseModel

from agents import llm


def _vllm_up() -> bool:
    try:
        return httpx.get("http://localhost:8000/health", timeout=2).status_code == 200
    except httpx.HTTPError:
        return False


pytestmark = [pytest.mark.llm, pytest.mark.skipif(not _vllm_up(), reason="vLLM not running on :8000")]


async def test_reasoning_on_returns_separate_reasoning(events):
    call = await llm.chat("test", [{"role": "user", "content": "Is 91 prime? Answer yes or no."}],
                          project_id="t", max_tokens=4000)
    assert call.reasoning and "no" in call.output.lower()
    assert call.tokens_in > 0 and call.tokens_out > 0 and events[-1].type == "llm_call"


async def test_reasoning_off_has_no_reasoning(events):
    call = await llm.chat("test", [{"role": "user", "content": "Say OK."}], project_id="t",
                          reasoning=False, max_tokens=50)
    assert not call.reasoning and call.output


async def test_schema_is_enforced(events):
    class Verdict(BaseModel):
        verdict: str
        confidence: float

    call = await llm.chat("test", [{"role": "user", "content": "Is the sky blue? Give a verdict and confidence."}],
                          project_id="t", schema=Verdict, max_tokens=4000)
    parsed = Verdict.model_validate_json(call.output)
    assert parsed.verdict.strip() and isinstance(parsed.confidence, float)
