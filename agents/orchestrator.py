"""Orchestrator: the three functions the backend calls (PLAN.md section 4).

    start_run(project_id)                 preprocess, then open the intake chat
    handle_user_message(project_id, text) intake answers, later Q&A
    stop_run(project_id)                  cancel everything, stop kernels

All three return quickly; work runs in background tasks and reports through
emit(). The backend owns the database; this module keeps per-project state in
memory.

Project files (the backend creates the folder and puts the dataset there):
    $DATA_ROOT/<project_id>/dataset.h5ad   uploaded file, or a hard link / copy of a preset
    $DATA_ROOT/<project_id>/processed.h5ad + dataset_summary.json   written here
Preprocessing is cached by file hash in $DATA_ROOT/_cache/, so presets start instantly.

End-to-end test on the box:  uv run python -m agents.orchestrator
"""

import asyncio
import hashlib
import json
import logging
import os
import traceback
from dataclasses import dataclass, field
from pathlib import Path

from agents import intake, literature, prompting, reporter, results
from agents.hypothesis import RunContext, plan_hypotheses, run_hypothesis
from sandbox import kernel_manager as km
from shared.events import Event, EventType, emit
from shared.schemas import Brief, ChatMessage, Finding, Hypothesis, Role

DATA_ROOT = Path(os.environ.get("DATA_ROOT", "/home/ubuntu/workspace/data"))
SANDBOX_DIR = Path(__file__).resolve().parent.parent / "sandbox"
N_HYPOTHESES = int(os.environ.get("N_HYPOTHESES", "3"))
# Search Europe PMC for literature (abstracts) unless turned off with SCRAP_ONLINE_SEARCH=0.
ONLINE_SEARCH = os.environ.get("SCRAP_ONLINE_SEARCH", "1") != "0"
log = logging.getLogger("scrap.orchestrator")


@dataclass
class _Run:
    project_id: str
    project_dir: Path
    stage: str = "starting"  # preprocess -> intake -> analysis -> done | stopped | failed
    summary: dict | None = None
    brief: Brief | None = None
    chat: list[ChatMessage] = field(default_factory=list)
    hypotheses: list[Hypothesis] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    background: str = ""
    sources: list[str] = field(default_factory=list)  # source ids the literature agent searched
    report: str | None = None
    prefix: str = ""  # shared prompt prefix, set once the brief is final
    tasks: set[asyncio.Task] = field(default_factory=set)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


_runs: dict[str, _Run] = {}


# --- the backend's interface ---

async def start_run(project_id: str) -> None:
    run = _runs.get(project_id)
    if run and run.stage not in ("stopped", "failed", "done"):
        return
    run = _runs[project_id] = _Run(project_id, DATA_ROOT / project_id)
    _spawn(run, _begin(run))


def can_answer(project_id: str) -> bool:
    """True if questions can be answered without starting a run: a run in memory, or a
    saved one (project_state.json) whose analysis got going, e.g. before a server restart."""
    run = _runs.get(project_id)
    if run is not None:
        return run.stage not in ("stopped", "failed") or bool(run.prefix)
    return _restore(project_id) is not None


async def handle_user_message(project_id: str, text: str) -> None:
    run = _runs.get(project_id)
    if run is None:
        run = _restore(project_id)
        if run is None:
            raise KeyError(f"No run for project {project_id}; call start_run first.")
        _runs[project_id] = run
    run.chat.append(ChatMessage(project_id=project_id, role=Role.user, content=text))
    if run.stage in ("starting", "preprocess", "intake"):
        _spawn(run, _intake_turn(run))
    else:
        _spawn(run, _answer(run, text))


async def stop_run(project_id: str) -> None:
    run = _runs.get(project_id)
    if run is None:
        return
    run.stage = "stopped"
    for task in list(run.tasks):
        task.cancel()
    await asyncio.gather(*run.tasks, return_exceptions=True)
    await asyncio.gather(*(km.stop_kernel(h.id) for h in run.hypotheses))
    _save(run)
    _stage_done(run, "stopped", "Run stopped by the user.")


# --- stages ---

async def _begin(run: _Run) -> None:
    run.stage = "preprocess"
    run.summary = await _ensure_processed(run.project_dir)
    _save(run)
    _stage_done(run, "preprocess", f"{run.summary['n_cells']} cells x {run.summary['n_genes']} genes ready.")
    run.brief = Brief(project_id=run.project_id, online_search=ONLINE_SEARCH)
    run.stage = "intake"
    await _intake_turn(run)


async def _intake_turn(run: _Run) -> None:
    async with run.lock:  # one intake reply at a time, in message order
        while run.summary is None:  # user wrote before preprocessing finished
            await asyncio.sleep(1)
        if run.stage != "intake":
            return
        # Reply to something new: the opening (empty chat) or a user message. When the first
        # message both starts the run and asks a question, two turns queue up; the second
        # finds the question already answered and stays quiet.
        if run.chat and run.chat[-1].role != Role.user:
            return
        try:
            result = await intake.turn(run.project_id, run.summary, run.brief, run.chat)
        except Exception:
            # One bad model reply must not end the run: say so and let the user answer again.
            log.exception("Intake turn failed for %s", run.project_id)
            _say(run, "Sorry, I lost my train of thought there. Could you say that again?")
            return
        run.brief = Brief(project_id=run.project_id, online_search=run.brief.online_search,
                          **result.brief.model_dump())
        emit(Event(type=EventType.brief_updated, project_id=run.project_id, payload=run.brief))
        _save(run)
        issues = intake.problems(run.brief, run.summary)
        _say(run, result.reply)
        if result.ready and not issues:
            run.stage = "analysis"
            _stage_done(run, "intake", "Brief confirmed; starting analysis.")
            _spawn(run, _analyze(run))
        elif result.ready:
            log.info("Intake said ready but brief has problems: %s", issues)


async def _analyze(run: _Run) -> None:
    run.prefix = prompting.shared_prefix(run.summary, run.brief)
    ctx = RunContext(run.project_id, run.project_dir, run.brief, run.summary, run.prefix)
    try:
        background, searched = await literature.background(
            run.project_id, run.project_dir, ctx.prefix, run.brief.goals, online=run.brief.online_search)
    except Exception:
        log.exception("Literature background failed; planning without it")
        background, searched = "", []
    run.background, run.sources = background, searched
    if background:
        (run.project_dir / "background.md").write_text(background)
        _save(run)
        _stage_done(run, "literature", f"Background from {len(searched)} sources:\n{background}")
    hypotheses = await plan_hypotheses(ctx, N_HYPOTHESES, background, past=run.hypotheses)
    run.hypotheses += hypotheses
    _save(run)
    _stage_done(run, "planning", "Testing: " + "; ".join(h.title for h in hypotheses))

    async def one(h: Hypothesis) -> Finding | None:
        try:
            return await run_hypothesis(ctx, h)
        finally:  # refresh the project page as each hypothesis finishes
            _save(run)

    outcomes = await asyncio.gather(*(one(h) for h in hypotheses), return_exceptions=True)
    for h, r in zip(hypotheses, outcomes):
        if isinstance(r, Finding):
            run.findings.append(r)
        elif isinstance(r, BaseException):
            log.error("Hypothesis %s failed: %s", h.id, "".join(traceback.format_exception(r)))
    approved = [f for f in run.findings if f.critic_verdict == "approve"]
    _stage_done(run, "analysis", f"{len(hypotheses)} hypotheses tested, {len(approved)} findings approved.")

    text = await reporter.report(run.project_id, run.prefix, run.background, run.hypotheses, run.findings)
    (run.project_dir / "report.md").write_text(text)
    run.report, run.stage = text, "done"
    _save(run)
    _say(run, text)
    _stage_done(run, "report", text)


async def _answer(run: _Run, text: str) -> None:
    """Q&A over results. Works mid-run too: it answers from whatever has finished so far."""
    if not run.prefix:
        _say(run, f"The analysis hasn't started yet (stage: {run.stage}).")
        return
    history = [(m.role.value, m.content) for m in run.chat[:-1]]
    try:
        reply = await reporter.answer(run.project_id, run.prefix, run.background, run.hypotheses,
                                      run.findings, history, text, progress=_progress(run))
    except Exception:
        log.exception("Answer failed for %s", run.project_id)
        reply = "Sorry, I couldn't answer that just now. Could you ask again?"
    _say(run, reply)


_STAGE_TEXT = {"analysis": "The analysis is still running; hypotheses without a finding are not finished yet.",
               "done": "The analysis is finished.", "stopped": "The run was stopped before it finished.",
               "failed": "The run failed before it finished."}


def _progress(run: _Run) -> str:
    """What has been done so far, for the reporter: stage and per-status hypothesis counts."""
    counts: dict[str, int] = {}
    for h in run.hypotheses:
        status = getattr(h.status, "value", h.status)
        counts[status] = counts.get(status, 0) + 1
    tally = ", ".join(f"{n} {s}" for s, n in counts.items()) or "none planned yet"
    lit = f"Literature: background from {len(run.sources)} sources." if run.sources else "Literature: none searched."
    return f"{_STAGE_TEXT.get(run.stage, f'Stage: {run.stage}.')} Hypotheses: {tally}. {lit}"


def _restore(project_id: str) -> _Run | None:
    """A finished (or interrupted) run rebuilt from project_state.json, for answering questions."""
    root = DATA_ROOT / project_id
    try:
        state = json.loads((root / "project_state.json").read_text())
        summary = json.loads((root / "dataset_summary.json").read_text())
    except (OSError, ValueError):
        return None
    if not state.get("brief") or not state.get("hypotheses"):
        return None  # intake never finished: nothing to answer from
    brief = Brief(**state["brief"])
    hypotheses, findings = [], []
    for entry in state["hypotheses"]:
        hypotheses.append(Hypothesis(**entry["hypothesis"]))
        if (entry.get("analysis") or {}).get("finding"):
            findings.append(Finding(**entry["analysis"]["finding"]))
    stage = "done" if state.get("report") else "stopped"
    return _Run(project_id, root, stage=stage, summary=summary, brief=brief, hypotheses=hypotheses,
                findings=findings, background=state.get("background") or "",
                sources=state.get("sources_searched") or [], report=state.get("report"),
                prefix=prompting.shared_prefix(summary, brief))


# --- helpers ---

def _save(run: _Run) -> None:
    """Refresh project_state.json for the app. Best-effort: never fails the run."""
    try:
        results.write_state(run.project_dir, run.project_id, run.stage, run.brief, run.summary,
                            run.background, run.sources, run.hypotheses, run.report)
    except Exception:
        log.exception("Could not write project_state.json for %s", run.project_id)


def _say(run: _Run, text: str) -> None:
    msg = ChatMessage(project_id=run.project_id, role=Role.assistant, content=text)
    run.chat.append(msg)
    emit(Event(type=EventType.chat_reply, project_id=run.project_id, payload=msg))


def _stage_done(run: _Run, stage: str, summary: str) -> None:
    emit(Event(type=EventType.stage_done, project_id=run.project_id,
               payload={"stage": stage, "summary": summary}))


def _spawn(run: _Run, coro) -> None:
    task = asyncio.create_task(coro)
    run.tasks.add(task)

    def done(t: asyncio.Task) -> None:
        run.tasks.discard(t)
        if not t.cancelled() and t.exception():
            run.stage = "failed"
            log.error("Run %s failed:\n%s", run.project_id, "".join(traceback.format_exception(t.exception())))
            _stage_done(run, "failed", f"{type(t.exception()).__name__}: {t.exception()}")
    task.add_done_callback(done)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


async def _ensure_processed(project_dir: Path) -> dict:
    """Make processed.h5ad + dataset_summary.json exist in project_dir; return the summary."""
    summary_path = project_dir / "dataset_summary.json"
    if not summary_path.exists():
        source = project_dir / "dataset.h5ad"
        if not source.exists():
            raise FileNotFoundError(f"Put the dataset at {source}")
        cache = DATA_ROOT / "_cache" / await asyncio.to_thread(_sha256, source)
        if not (cache / "dataset_summary.json").exists():
            proc = await asyncio.create_subprocess_exec(
                "docker", "run", "--rm", "--network", "none",
                "-v", f"{DATA_ROOT}:/data", "-v", f"{SANDBOX_DIR}:/app:ro", km.IMAGE,
                "python", "/app/preprocess.py",
                f"/data/{source.relative_to(DATA_ROOT)}", f"/data/{cache.relative_to(DATA_ROOT)}",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
            out, _ = await proc.communicate()
            if proc.returncode != 0:
                raise RuntimeError(f"Preprocessing failed:\n{out.decode()[-3000:]}")
        for name in ("processed.h5ad", "dataset_summary.json", "umap_overview.png", "umap_points.json"):
            dest = project_dir / name
            if not dest.exists() and (cache / name).exists():
                os.link(cache / name, dest)  # hard link: no copy, and it resolves inside containers
    return json.loads(summary_path.read_text())


# --- end-to-end test: plays the backend and the user ---

async def _demo() -> None:
    import time

    import httpx

    from shared.events import set_sink

    replies: asyncio.Queue = asyncio.Queue()
    done = asyncio.Event()
    peak = {"running": 0.0}

    def show(e: Event) -> None:
        p = e.payload
        if e.type == EventType.chat_reply:
            print(f"\nASSISTANT: {p['content']}\n")
            replies.put_nowait(p["content"])
        elif e.type == EventType.brief_updated:
            print("  brief:", {k: v for k, v in p.items() if v and k != "project_id"})
        elif e.type == EventType.stage_done:
            print(f"== stage_done {p['stage']}: {p['summary']}")
            if p["stage"] in ("report", "failed", "stopped"):
                done.set()
        elif e.type == EventType.finding:
            print(f"  FINDING [{p['critic_verdict']}] {p['claim']}  (p_adj={p['p_adj']}, effect={p['effect_size']})")
        elif e.type == EventType.hypothesis_status and p["status"] in ("approved", "rejected", "failed"):
            print(f"  hypothesis {p['status']}: {p['title']}")
    set_sink(show)

    def metric(name: str) -> float:
        for line in httpx.get("http://localhost:8000/metrics").text.splitlines():
            if line.startswith(name + "{"):
                return float(line.split()[-1])
        return 0.0

    async def watch() -> None:
        while not done.is_set():
            peak["running"] = max(peak["running"], metric("vllm:num_requests_running"))
            await asyncio.sleep(0.5)

    pid = f"demo-{int(time.time())}"
    project_dir = DATA_ROOT / pid
    project_dir.mkdir(parents=True)
    os.link(DATA_ROOT / "raw" / "covid_pbmc_wilk2020.h5ad", project_dir / "dataset.h5ad")
    cached0, queried0, t0 = metric("vllm:prompt_tokens_cached_total"), metric("vllm:prompt_tokens_total"), time.time()
    watcher = asyncio.create_task(watch())

    await start_run(pid)
    print("USER: (creates project)")
    await replies.get()
    answer = ("Yes, those columns are right. I want to understand how innate immune cells, especially "
              "monocytes, respond differently in hospitalized COVID-19 patients versus healthy donors. "
              "The original paper (Wilk et al. 2020) reported an interferon-stimulated gene signature "
              "and HLA class II downregulation in monocytes.")
    print(f"USER: {answer}")
    await handle_user_message(pid, answer)
    for _ in range(3):
        await asyncio.wait([asyncio.create_task(replies.get()), asyncio.create_task(done.wait())],
                           return_when=asyncio.FIRST_COMPLETED)
        if _runs[pid].stage != "intake":
            break
        print("USER: Looks good, please start the analysis.")
        await handle_user_message(pid, "Looks good, please start the analysis.")
    await done.wait()
    watcher.cancel()
    while not replies.empty():  # drop earlier replies (intake, report)
        replies.get_nowait()
    question = "Which result is strongest, and is it already known from the literature?"
    print(f"USER: {question}")
    await handle_user_message(pid, question)
    await replies.get()

    cached = metric("vllm:prompt_tokens_cached_total") - cached0
    prompt = metric("vllm:prompt_tokens_total") - queried0
    print(f"\nTotal {time.time() - t0:.0f}s. Peak concurrent LLM requests: {peak['running']:.0f}. "
          f"Prompt tokens served from prefix cache: {cached:.0f}/{prompt:.0f} ({100 * cached / max(prompt, 1):.0f}%).")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    asyncio.run(_demo())
