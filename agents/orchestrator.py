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

from agents import intake, prompting
from agents.hypothesis import RunContext, plan_hypotheses, run_hypothesis
from sandbox import kernel_manager as km
from shared.events import Event, EventType, emit
from shared.schemas import Brief, ChatMessage, Finding, Hypothesis, Role

DATA_ROOT = Path(os.environ.get("DATA_ROOT", "/home/ubuntu/workspace/data"))
SANDBOX_DIR = Path(__file__).resolve().parent.parent / "sandbox"
N_HYPOTHESES = int(os.environ.get("N_HYPOTHESES", "3"))
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
    tasks: set[asyncio.Task] = field(default_factory=set)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


_runs: dict[str, _Run] = {}


# --- the backend's interface ---

async def start_run(project_id: str) -> None:
    run = _runs.get(project_id)
    if run and run.stage not in ("stopped", "failed"):
        return
    run = _runs[project_id] = _Run(project_id, DATA_ROOT / project_id)
    _spawn(run, _begin(run))


async def handle_user_message(project_id: str, text: str) -> None:
    run = _runs.get(project_id)
    if run is None:
        raise KeyError(f"No run for project {project_id}; call start_run first.")
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
    _stage_done(run, "stopped", "Run stopped by the user.")


# --- stages ---

async def _begin(run: _Run) -> None:
    run.stage = "preprocess"
    run.summary = await _ensure_processed(run.project_dir)
    _stage_done(run, "preprocess", f"{run.summary['n_cells']} cells x {run.summary['n_genes']} genes ready.")
    run.brief = Brief(project_id=run.project_id)
    run.stage = "intake"
    await _intake_turn(run)


async def _intake_turn(run: _Run) -> None:
    async with run.lock:  # one intake reply at a time, in message order
        while run.summary is None:  # user wrote before preprocessing finished
            await asyncio.sleep(1)
        if run.stage != "intake":
            return
        result = await intake.turn(run.project_id, run.summary, run.brief, run.chat)
        run.brief = Brief(project_id=run.project_id, online_search=run.brief.online_search,
                          **result.brief.model_dump())
        emit(Event(type=EventType.brief_updated, project_id=run.project_id, payload=run.brief))
        issues = intake.problems(run.brief, run.summary)
        _say(run, result.reply)
        if result.ready and not issues:
            run.stage = "analysis"
            _stage_done(run, "intake", "Brief confirmed; starting analysis.")
            _spawn(run, _analyze(run))
        elif result.ready:
            log.info("Intake said ready but brief has problems: %s", issues)


async def _analyze(run: _Run) -> None:
    ctx = RunContext(run.project_id, run.project_dir, run.brief, run.summary,
                     prompting.shared_prefix(run.summary, run.brief))
    background = ""  # literature agent (step 11) fills this in
    hypotheses = await plan_hypotheses(ctx, N_HYPOTHESES, background, past=run.hypotheses)
    run.hypotheses += hypotheses
    _stage_done(run, "planning", "Testing: " + "; ".join(h.title for h in hypotheses))

    results = await asyncio.gather(*(run_hypothesis(ctx, h) for h in hypotheses), return_exceptions=True)
    for h, r in zip(hypotheses, results):
        if isinstance(r, Finding):
            run.findings.append(r)
        elif isinstance(r, BaseException):
            log.error("Hypothesis %s failed: %s", h.id, "".join(traceback.format_exception(r)))
    approved = [f for f in run.findings if f.critic_verdict == "approve"]
    run.stage = "done"
    _stage_done(run, "analysis", f"{len(hypotheses)} hypotheses tested, {len(approved)} findings approved.")


async def _answer(run: _Run, text: str) -> None:
    # Q&A over results is the reporter agent (step 12); until then, report status.
    approved = [f for f in run.findings if f.critic_verdict == "approve"]
    lines = [f"Stage: {run.stage}. {len(run.hypotheses)} hypotheses, {len(approved)} approved findings."]
    lines += [f"- {f.claim}" for f in approved]
    _say(run, "\n".join(lines))


# --- helpers ---

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
        for name in ("processed.h5ad", "dataset_summary.json", "umap_overview.png"):
            dest = project_dir / name
            if not dest.exists():
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
            if p["stage"] in ("analysis", "failed", "stopped"):
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

    cached = metric("vllm:prompt_tokens_cached_total") - cached0
    prompt = metric("vllm:prompt_tokens_total") - queried0
    print(f"\nTotal {time.time() - t0:.0f}s. Peak concurrent LLM requests: {peak['running']:.0f}. "
          f"Prompt tokens served from prefix cache: {cached:.0f}/{prompt:.0f} ({100 * cached / max(prompt, 1):.0f}%).")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    asyncio.run(_demo())
