"""Single-agent baseline: one Lightning agent, same data and helpers, no planner,
reader, critic or parallelism. It writes cells in one growing conversation and
lists its findings at the end. Isolates what the multi-agent structure adds.
"""

import json
import re

from agents import prompting
from agents.hypothesis import RunContext
from agents.llm import chat
from sandbox import kernel_manager as km
from shared.schemas import Finding

MAX_CELLS = 15


async def run_baseline(ctx: RunContext, run_id: str = "baseline") -> list[Finding]:
    await km.start_kernel(run_id, ctx.project_id, ctx.project_dir)
    msgs = prompting.messages(ctx.prefix, "baseline", f"Goals: {ctx.brief.goals}\nBegin.", max_cells=MAX_CELLS)
    try:
        for _ in range(MAX_CELLS + 1):
            call = await chat("baseline", msgs, project_id=ctx.project_id, hypothesis_id=run_id)
            msgs.append({"role": "assistant", "content": call.output})
            if "FINAL" in call.output:
                return _parse_findings(call.output, run_id)
            blocks = re.findall(r"```(?:python)?\s*\n(.*?)```", call.output, re.S)
            if not blocks:
                msgs.append({"role": "user", "content": "Reply with one python code block, or FINAL and the JSON."})
                continue
            cell = await km.run_cell(run_id, blocks[-1].strip())
            out = (cell.stdout[-3000:] or "(no output)") + (f"\n[stderr]\n{cell.stderr[-2000:]}" if cell.stderr else "")
            msgs.append({"role": "user", "content": f"Output ({cell.status}):\n{out}"})
        msgs.append({"role": "user", "content": "Cell budget used up. Reply FINAL and the JSON now."})
        call = await chat("baseline", msgs, project_id=ctx.project_id, hypothesis_id=run_id)
        return _parse_findings(call.output, run_id)
    finally:
        await km.stop_kernel(run_id)


def _parse_findings(text: str, run_id: str) -> list[Finding]:
    match = re.search(r"\[.*\]", text.split("FINAL", 1)[-1], re.S)
    try:
        items = json.loads(match.group(0)) if match else []
    except json.JSONDecodeError:
        return []
    return [Finding(hypothesis_id=run_id, claim=str(i.get("claim", "")), test=str(i.get("test", "")),
                    statistic=_num(i.get("statistic")), p_adj=_num(i.get("p_adj")),
                    effect_size=_num(i.get("effect_size"))) for i in items if isinstance(i, dict)]


def _num(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
