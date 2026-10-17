"""Planning, and the per-hypothesis loop: code -> run -> read -> finding -> checks -> critic.

Test on the COVID dataset (vLLM running):  uv run python -m agents.hypothesis
"""

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from agents import checks, literature, prompting, results
from agents.llm import chat
from sandbox import kernel_manager as km
from shared.events import Event, EventType, emit
from shared.schemas import Brief, CellStatus, CodeCell, CriticVerdict, Finding, Hypothesis, HypothesisStatus

MAX_FIX_ATTEMPTS = 3  # coder retries per step after an error
MAX_REVISIONS = 1  # extra cells the critic may request
CONTEXT_CHARS = 2500  # output per cell shown to other agents
log = logging.getLogger("scrap.hypothesis")


@dataclass
class RunContext:
    project_id: str
    project_dir: Path
    brief: Brief
    summary: dict  # dataset_summary.json
    prefix: str  # shared prompt prefix

    @classmethod
    def load(cls, project_id: str, project_dir: str | Path, brief: Brief) -> "RunContext":
        project_dir = Path(project_dir)
        summary = json.loads((project_dir / "dataset_summary.json").read_text())
        return cls(project_id, project_dir, brief, summary, prompting.shared_prefix(summary, brief))


# --- structured outputs (vLLM enforces these JSON schemas) ---

class PlannedHypothesis(BaseModel):
    title: str
    rationale: str
    plan_steps: list[str] = Field(min_length=2, max_length=4)  # vLLM enforces this as minItems/maxItems


class Plan(BaseModel):
    hypotheses: list[PlannedHypothesis]


class DraftFinding(BaseModel):
    claim: str
    test: str
    statistic: float | None
    p_adj: float | None
    effect_size: float | None
    figure_cell: int | None


class Review(BaseModel):
    verdict: Literal["approve", "revise", "reject"]
    issues: list[str]
    fix: str


# --- helpers ---

def _set_status(ctx: RunContext, h: Hypothesis, status: HypothesisStatus) -> None:
    h.status = status
    emit(Event(type=EventType.hypothesis_status, project_id=ctx.project_id, payload=h))


def _show_cell(cell: CodeCell) -> str:
    out = cell.stdout[-CONTEXT_CHARS:] or "(no output)"
    if cell.stderr:
        out += "\n[stderr]\n" + cell.stderr[-CONTEXT_CHARS:]
    return f"[cell {cell.index}]\n```python\n{cell.source}\n```\nOutput:\n{out}"


def _plan_text(h: Hypothesis) -> str:
    return "\n".join(f"{i}. {s}" for i, s in enumerate(h.plan_steps, 1))


def _extract_code(text: str) -> str:
    blocks = re.findall(r"```(?:python)?\s*\n(.*?)```", text, re.S)
    return (blocks[-1] if blocks else text).strip()


# --- agents ---

async def plan_hypotheses(ctx: RunContext, n: int = 3, background: str = "",
                          past: list[Hypothesis] | None = None) -> list[Hypothesis]:
    user = f"Background:\n{background or '(none yet)'}\n\nPast hypotheses:\n" + (
        "\n".join(f"- {h.title} ({h.status})" for h in past or []) or "(none)")
    call = await chat("planner", prompting.messages(ctx.prefix, "planner", user, n=n),
                      project_id=ctx.project_id, schema=Plan)
    plan = Plan.model_validate_json(call.output)
    hypotheses = [Hypothesis(project_id=ctx.project_id, **p.model_dump()) for p in plan.hypotheses[:n]]
    for h in hypotheses:
        _set_status(ctx, h, HypothesisStatus.planning)
    return hypotheses


async def _code_step(ctx: RunContext, h: Hypothesis, step: str, done: list[CodeCell]) -> CodeCell:
    """Coder writes a cell for `step`; on error it sees the traceback and retries."""
    # Stable text first, so each step's prompt starts with the previous step's prompt
    # verbatim and vLLM can reuse its cached blocks. What changes goes last.
    history = "\n\n".join(_show_cell(c) for c in done) or "(no cells yet)"
    base = (f"Hypothesis: {h.title}\nPlan:\n{_plan_text(h)}\n\nPrevious cells:\n{history}\n\n"
            f"Current step: {step}")
    user, parent = base, None
    for _ in range(MAX_FIX_ATTEMPTS + 1):
        _set_status(ctx, h, HypothesisStatus.coding)
        call = await chat("coder", prompting.messages(ctx.prefix, "coder", user),
                          project_id=ctx.project_id, hypothesis_id=h.id, parent_call_id=parent)
        _set_status(ctx, h, HypothesisStatus.running)
        cell = await km.run_cell(h.id, _extract_code(call.output))
        if cell.status == CellStatus.ok:
            return cell
        user = f"{base}\n\nYour previous attempt failed:\n{_show_cell(cell)}\nFix the cause and write the cell again."
        parent = call.id
    return cell


async def _read(ctx: RunContext, h: Hypothesis, step: str, cell: CodeCell) -> str:
    call = await chat("reader", prompting.messages(ctx.prefix, "reader", f"Step: {step}\n\n{_show_cell(cell)}"),
                      project_id=ctx.project_id, hypothesis_id=h.id)
    return call.output.strip()


async def _write_finding(ctx: RunContext, h: Hypothesis, cells: list[CodeCell], notes: list[str]) -> DraftFinding:
    user = (f"Hypothesis: {h.title}\n\n" + "\n\n".join(_show_cell(c) for c in cells) +
            "\n\nReader notes:\n" + "\n".join(f"- {n}" for n in notes))
    call = await chat("finding", prompting.messages(ctx.prefix, "finding", user),
                      project_id=ctx.project_id, hypothesis_id=h.id, schema=DraftFinding)
    return DraftFinding.model_validate_json(call.output)


async def _critique(ctx: RunContext, h: Hypothesis, cells: list[CodeCell], draft: DraftFinding,
                    report: str) -> Review:
    # Fresh context: no planner rationale or reader notes, only what ran and what is claimed.
    user = ("Claimed finding:\n" + draft.model_dump_json(indent=2) + "\n\nCode and output:\n" +
            "\n\n".join(_show_cell(c) for c in cells) + f"\n\nAutomated checks:\n{report}")
    call = await chat("critic", prompting.messages(ctx.prefix, "critic", user),
                      project_id=ctx.project_id, hypothesis_id=h.id, schema=Review)
    return Review.model_validate_json(call.output)


async def run_hypothesis(ctx: RunContext, h: Hypothesis, critic: bool = True) -> Finding | None:
    """Run one hypothesis end to end. Emits status, cell, llm_call and finding events.

    critic=False skips checks and critique and approves whatever the finding writer
    claims; it exists only for the rigor benchmark.
    """
    await km.start_kernel(h.id, ctx.project_id, ctx.project_dir)
    cells, notes, labels = [], [], []  # labels[i] is the step that cells[i] carried out
    finding: Finding | None = None
    try:
        for step in h.plan_steps:
            cell = await _code_step(ctx, h, step, cells)
            if cell.status != CellStatus.ok:
                labels.append(step)
                cells.append(cell)
                notes.append("This step failed after every retry.")
                _set_status(ctx, h, HypothesisStatus.failed)
                return None
            labels.append(step)
            cells.append(cell)
            notes.append(await _read(ctx, h, step, cell))

        _set_status(ctx, h, HypothesisStatus.critiquing)
        draft = await _write_finding(ctx, h, cells, notes)
        if not critic:
            finding = Finding(hypothesis_id=h.id, critic_verdict=CriticVerdict.approve,
                              critic_notes="Critic disabled (benchmark).", **draft.model_dump(exclude={"figure_cell"}))
            _attach_files(ctx, h, finding, cells, draft.figure_cell)
            emit(Event(type=EventType.finding, project_id=ctx.project_id, payload=finding))
            _set_status(ctx, h, HypothesisStatus.approved)
            return finding
        design = checks.parse_design(await km.run_cell(h.id, checks.design_check_code(ctx.brief)))
        history: list[str] = []  # every critic round, so the rigor benchmark can count revisions
        for revision in range(MAX_REVISIONS + 1):
            finding = Finding(hypothesis_id=h.id, **draft.model_dump(exclude={"figure_cell"}))
            check_results = checks.run_checks(cells, finding, design)
            report = checks.format_report(check_results)
            review = await _critique(ctx, h, cells, draft, report)
            if review.verdict != "revise" or revision == MAX_REVISIONS:
                break
            history.append(f"Round {revision + 1}: revise. " + " ".join(review.issues) + f" Fix requested: {review.fix}")
            step = f"Statistics critic requested: {review.fix}"
            cell = await _code_step(ctx, h, step, cells)
            if cell.status == CellStatus.ok:
                labels.append(step)
                cells.append(cell)
                notes.append(await _read(ctx, h, step, cell))
                _set_status(ctx, h, HypothesisStatus.critiquing)
                draft = await _write_finding(ctx, h, cells, notes)

        # An unresolved revise counts as a reject: the critic did not sign off.
        finding.critic_verdict = CriticVerdict.approve if review.verdict == "approve" else CriticVerdict.reject
        final = f"Final: {review.verdict}. " + " ".join(review.issues) + (f" Fix requested: {review.fix}" if review.fix else "")
        blocked = [c for c in check_results if c.name in checks.BLOCKING and c.status == "fail"]
        if blocked:  # hard rules beat the critic's judgment
            finding.critic_verdict = CriticVerdict.reject
            final += " Overridden to reject by automated checks: " + " ".join(c.detail for c in blocked)
        finding.critic_notes = "\n".join(history + [final.strip()])
        _attach_files(ctx, h, finding, cells, draft.figure_cell)
        if finding.critic_verdict == CriticVerdict.approve:
            try:  # novelty is a bonus; never lose a finding over it
                await literature.novelty(ctx.project_id, ctx.project_dir, ctx.prefix, finding,
                                         online=ctx.brief.online_search)
            except Exception:
                log.exception("Novelty check failed for %s", h.id)
        emit(Event(type=EventType.finding, project_id=ctx.project_id, payload=finding))
        _set_status(ctx, h, HypothesisStatus.approved if finding.critic_verdict == CriticVerdict.approve
                    else HypothesisStatus.rejected)
        return finding
    except Exception:
        _set_status(ctx, h, HypothesisStatus.failed)
        raise
    finally:
        await km.stop_kernel(h.id)
        try:  # the record for the project page; never let saving it break a run
            results.save_analysis(ctx.project_dir, h, list(zip(labels, cells, notes)), finding)
        except Exception:
            log.exception("Could not save analysis.json for %s", h.id)


def _attach_files(ctx: RunContext, h: Hypothesis, finding: Finding, cells: list[CodeCell],
                  figure_cell: int | None) -> None:
    """Point the finding at its notebook and best figure (the cell it cites, else the last plot)."""
    figs = {c.index: c.figure_paths for c in cells if c.figure_paths}
    pick = figs.get(figure_cell) or (list(figs.values())[-1] if figs else [])
    finding.figure_path = pick[0] if pick else None
    finding.notebook_path = str(ctx.project_dir / "hypotheses" / h.id / f"{h.id}.ipynb")


async def _demo() -> None:
    """Step 8 check: plan one interferon hypothesis on COVID PBMCs and run it."""
    import time
    from shared.events import set_sink

    def show(e: Event) -> None:
        p = e.payload
        if e.type == EventType.llm_call:
            print(f"  llm  {p['agent']:<8} {p['latency_ms']:>6} ms  {p['tokens_in']:>6} in  {p['tokens_out']:>5} out")
        elif e.type == EventType.cell_finished:
            print(f"  cell {p['index']} {p['status']}" + (f"  figs={len(p['figure_paths'])}" if p["figure_paths"] else ""))
        elif e.type == EventType.hypothesis_status:
            print(f"  -> {p['status']}")
    set_sink(show)

    brief = Brief(project_id="covid-demo", organism="human", condition_column="disease",
                  condition_labels=["COVID-19", "normal"], donor_column="donor_id",
                  celltype_column="cell.type.coarse", gene_id_format="symbol",
                  goals="Characterize how the innate immune response in blood differs between "
                        "hospitalized COVID-19 patients and healthy donors.")
    ctx = RunContext.load("covid-demo", "/home/ubuntu/workspace/data/covid_pbmc", brief)
    start = time.perf_counter()
    [h] = await plan_hypotheses(ctx, n=1, background=(
        "Severe viral infections typically induce type I interferon signaling in monocytes."))
    print(f"\nHYPOTHESIS: {h.title}\n{_plan_text(h)}\n")
    finding = await run_hypothesis(ctx, h)
    print(f"\nFINDING ({time.perf_counter() - start:.0f}s total):")
    print(finding.model_dump_json(indent=2) if finding else "none (hypothesis failed)")


if __name__ == "__main__":
    import asyncio
    asyncio.run(_demo())
