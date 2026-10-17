"""agents/orchestrator.py: the backend's interface, stage flow, and failure handling."""

import asyncio
import json
import os
from pathlib import Path

import pytest

from agents import intake, literature, orchestrator as orch, reporter
from agents.intake import BriefFields, IntakeTurn
from sandbox import kernel_manager as km
from shared.schemas import Finding, Hypothesis


async def wait_for(events, predicate, timeout=5.0):
    for _ in range(int(timeout / 0.01)):
        hits = [e for e in events if predicate(e)]
        if hits:
            return hits[-1]
        await asyncio.sleep(0.01)
    raise AssertionError(f"timed out; events so far: {[(e.type, e.payload.get('stage')) for e in events]}")


def stage(name):
    return lambda e: e.type == "stage_done" and e.payload["stage"] == name


def stages(events) -> list[str]:
    return [e.payload["stage"] for e in events if e.type == "stage_done"]


GOOD = dict(organism="human", condition_column="disease", condition_labels=["COVID-19", "normal"],
            donor_column="donor_id", celltype_column="cell.type.coarse", gene_id_format="symbol",
            prior_analyses=["Wilk 2020"], goals="monocytes", notes="")


def turn(ready: bool, reply="ok", **overrides) -> IntakeTurn:
    return IntakeTurn(brief=BriefFields(**{**GOOD, **overrides}), reply=reply, ready=ready)


@pytest.fixture
def env(monkeypatch, tmp_path, events, summary):
    """A project folder that is already preprocessed, with every agent faked."""
    monkeypatch.setattr(orch, "DATA_ROOT", tmp_path)
    orch._runs.clear()
    project = tmp_path / "p1"
    project.mkdir()
    (project / "dataset_summary.json").write_text(json.dumps(summary))

    state = type("S", (), {})()
    state.events, state.project, state.tmp = events, project, tmp_path
    state.intake_turns = []          # scripted IntakeTurns, consumed in order
    state.intake_histories = []
    state.planned = [Hypothesis(project_id="p1", title=f"H{i}", plan_steps=["a", "b"]) for i in range(3)]
    state.results = {}               # hypothesis title -> Finding | Exception
    state.stopped_kernels = []
    state.answers = []

    async def fake_turn(project_id, summary_, brief, history):
        state.intake_histories.append([m.content for m in history])
        return state.intake_turns.pop(0)

    async def fake_plan(ctx, n, background, past=None):
        state.background_seen = background
        return state.planned[:n]

    async def fake_run(ctx, h, critic=True):
        r = state.results.get(h.title)
        if isinstance(r, BaseException):
            raise r
        if r == "hang":
            await asyncio.Event().wait()
        return r or Finding(hypothesis_id=h.id, claim=f"{h.title} holds", test="t", p_adj=0.01,
                            effect_size=1.0, critic_verdict="approve")

    async def fake_background(project_id, project_dir, prefix, goals, online=False):
        return "Background [wilk2020 p.2].", ["wilk2020"]

    async def fake_report(project_id, prefix, background, hypotheses, findings):
        return f"# Report\n{len(findings)} findings"

    async def fake_answer(project_id, prefix, background, hypotheses, findings, history, question):
        state.answers.append((question, history))
        return f"Answer to: {question}"

    async def fake_stop(hid):
        state.stopped_kernels.append(hid)

    monkeypatch.setattr(intake, "turn", fake_turn)
    monkeypatch.setattr(orch, "plan_hypotheses", fake_plan)
    monkeypatch.setattr(orch, "run_hypothesis", fake_run)
    monkeypatch.setattr(literature, "background", fake_background)
    monkeypatch.setattr(reporter, "report", fake_report)
    monkeypatch.setattr(reporter, "answer", fake_answer)
    monkeypatch.setattr(km, "stop_kernel", fake_stop)
    yield state
    for run in orch._runs.values():
        for t in run.tasks:
            t.cancel()
    orch._runs.clear()


async def test_full_run(env):
    env.intake_turns = [turn(False, "What are your goals?"), turn(True, "Starting.")]
    await orch.start_run("p1")
    await wait_for(env.events, lambda e: e.type == "chat_reply")
    assert orch._runs["p1"].stage == "intake"

    await orch.handle_user_message("p1", "Monocytes in COVID vs healthy.")
    await wait_for(env.events, stage("report"))

    assert stages(env.events) == ["preprocess", "intake", "literature", "planning", "analysis", "report"]
    assert env.intake_histories == [[], ["What are your goals?", "Monocytes in COVID vs healthy."]]
    assert env.background_seen == "Background [wilk2020 p.2]."
    assert (env.project / "report.md").read_text() == "# Report\n3 findings"
    run = orch._runs["p1"]
    assert run.stage == "done" and len(run.findings) == 3 and run.prefix
    briefs = [e for e in env.events if e.type == "brief_updated"]
    assert len(briefs) == 2 and briefs[-1].payload["condition_column"] == "disease"
    assert [e.payload["content"] for e in env.events if e.type == "chat_reply"][-1].startswith("# Report")
    analysis = next(e for e in env.events if stage("analysis")(e))
    assert analysis.payload["summary"] == "3 hypotheses tested, 3 findings approved."


async def test_start_run_is_idempotent(env):
    env.intake_turns = [turn(False)]
    await orch.start_run("p1")
    first = orch._runs["p1"]
    await orch.start_run("p1")
    assert orch._runs["p1"] is first


async def test_message_before_start_raises(env):
    with pytest.raises(KeyError):
        await orch.handle_user_message("nope", "hi")


async def test_intake_ready_but_invalid_brief_keeps_chatting(env):
    env.intake_turns = [turn(False), turn(True, condition_column="not_a_column")]
    await orch.start_run("p1")
    await wait_for(env.events, lambda e: e.type == "chat_reply")
    await orch.handle_user_message("p1", "go")
    await wait_for(env.events, lambda e: e.type == "chat_reply" and e.payload["content"] == "ok"
                   and len([x for x in env.events if x.type == "chat_reply"]) == 2)
    await asyncio.sleep(0.05)
    assert orch._runs["p1"].stage == "intake" and "intake" not in stages(env.events)


async def test_online_search_flag_survives_intake(env):
    env.intake_turns = [turn(False), turn(True)]
    await orch.start_run("p1")
    await wait_for(env.events, lambda e: e.type == "chat_reply")
    orch._runs["p1"].brief.online_search = True
    await orch.handle_user_message("p1", "go")
    await wait_for(env.events, stage("report"))
    assert orch._runs["p1"].brief.online_search is True


async def test_questions_after_the_run_go_to_the_reporter(env):
    env.intake_turns = [turn(False), turn(True)]
    await orch.start_run("p1")
    await wait_for(env.events, lambda e: e.type == "chat_reply")
    await orch.handle_user_message("p1", "go")
    await wait_for(env.events, stage("report"))
    await orch.handle_user_message("p1", "Which result is strongest?")
    reply = await wait_for(env.events, lambda e: e.type == "chat_reply"
                           and e.payload["content"] == "Answer to: Which result is strongest?")
    question, history = env.answers[0]
    assert question == "Which result is strongest?"
    assert history[-1][1].startswith("# Report") and all(h[1] != question for h in history)
    assert reply.payload["role"] == "assistant"


async def test_answer_before_analysis_reports_stage(env):
    run = orch._Run("p1", env.project, stage="failed")
    await orch._answer(run, "hello")
    assert "hasn't started" in env.events[-1].payload["content"]


async def test_one_failing_hypothesis_does_not_fail_the_run(env):
    env.intake_turns = [turn(False), turn(True)]
    env.results = {"H1": RuntimeError("kernel died")}
    await orch.start_run("p1")
    await wait_for(env.events, lambda e: e.type == "chat_reply")
    await orch.handle_user_message("p1", "go")
    await wait_for(env.events, stage("report"))
    assert len(orch._runs["p1"].findings) == 2 and "failed" not in stages(env.events)


async def test_literature_failure_plans_without_background(env, monkeypatch):
    async def broken(*a, **k):
        raise RuntimeError("no GPU memory")
    monkeypatch.setattr(literature, "background", broken)
    env.intake_turns = [turn(False), turn(True)]
    await orch.start_run("p1")
    await wait_for(env.events, lambda e: e.type == "chat_reply")
    await orch.handle_user_message("p1", "go")
    await wait_for(env.events, stage("report"))
    assert env.background_seen == "" and "literature" not in stages(env.events)


async def test_stop_run_cancels_and_stops_kernels(env):
    env.intake_turns = [turn(False), turn(True)]
    env.results = {h.title: "hang" for h in env.planned}
    await orch.start_run("p1")
    await wait_for(env.events, lambda e: e.type == "chat_reply")
    await orch.handle_user_message("p1", "go")
    await wait_for(env.events, stage("planning"))
    await orch.stop_run("p1")
    run = orch._runs["p1"]
    assert run.stage == "stopped" and not run.tasks
    assert sorted(env.stopped_kernels) == sorted(h.id for h in env.planned)
    assert stages(env.events)[-1] == "stopped"


async def test_stop_unknown_project_is_a_no_op(env):
    await orch.stop_run("nope")


async def test_missing_dataset_fails_the_run(env):
    (env.tmp / "p2").mkdir()
    await orch.start_run("p2")
    failed = await wait_for(env.events, stage("failed"))
    assert "FileNotFoundError" in failed.payload["summary"] and orch._runs["p2"].stage == "failed"


async def test_failed_run_can_be_restarted(env):
    (env.tmp / "p2").mkdir()
    await orch.start_run("p2")
    await wait_for(env.events, stage("failed"))
    first = orch._runs["p2"]
    await orch.start_run("p2")
    assert orch._runs["p2"] is not first


# --- preprocessing cache ---

@pytest.fixture
def fake_docker(monkeypatch, env, summary):
    calls = []

    async def create_subprocess_exec(*args, **kwargs):
        calls.append(args)
        out_dir = env.tmp / args[-1].removeprefix("/data/")
        out_dir.mkdir(parents=True, exist_ok=True)
        for name in ("processed.h5ad", "umap_overview.png"):
            (out_dir / name).write_bytes(b"x")
        (out_dir / "dataset_summary.json").write_text(json.dumps(summary))

        class Proc:
            returncode = 0

            async def communicate(self):
                return b"done", None
        return Proc()

    monkeypatch.setattr(orch.asyncio, "create_subprocess_exec", create_subprocess_exec)
    return calls


async def test_preprocessing_runs_once_per_dataset_and_hard_links(env, fake_docker):
    for pid in ("a", "b"):
        d = env.tmp / pid
        d.mkdir()
        (d / "dataset.h5ad").write_bytes(b"same dataset bytes")
        summary = await orch._ensure_processed(d)
        assert summary["n_cells"] == 1000
    assert len(fake_docker) == 1
    assert fake_docker[0][:6] == ("docker", "run", "--rm", "--network", "none", "-v")
    a, b = env.tmp / "a" / "processed.h5ad", env.tmp / "b" / "processed.h5ad"
    assert os.stat(a).st_ino == os.stat(b).st_ino  # hard links to the cached file


async def test_preprocessing_failure_raises(env, monkeypatch):
    async def failing(*args, **kwargs):
        class Proc:
            returncode = 1

            async def communicate(self):
                return b"Traceback: bad file", None
        return Proc()
    monkeypatch.setattr(orch.asyncio, "create_subprocess_exec", failing)
    d = env.tmp / "c"
    d.mkdir()
    (d / "dataset.h5ad").write_bytes(b"broken")
    with pytest.raises(RuntimeError, match="bad file"):
        await orch._ensure_processed(d)


def test_sha256_is_stable(tmp_path):
    f = tmp_path / "x"
    f.write_bytes(b"abc")
    assert orch._sha256(f) == "ba7816bf8f01cfea" and len(orch._sha256(f)) == 16
