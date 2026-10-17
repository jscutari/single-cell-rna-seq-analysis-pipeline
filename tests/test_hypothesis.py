"""agents/hypothesis.py: planning and the code -> run -> read -> finding -> checks -> critic loop."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from agents import hypothesis as hyp
from agents import literature
from agents.hypothesis import DraftFinding, Plan, PlannedHypothesis, Review, RunContext
from sandbox import kernel_manager as km
from shared.schemas import CellStatus, CodeCell, Hypothesis

DESIGN = {"donors_per_condition": {"COVID-19": 7, "normal": 6}, "confounded": []}
CODE = "```python\ncounts, meta = pseudobulk(adata, 'donor_id', 'disease')\nres = deseq(counts, meta, 'a', 'b')\n```"


class FakeKernel:
    """Replaces sandbox.kernel_manager. Cell outcomes are scripted in order."""

    def __init__(self, outcomes=None, figures=None):
        self.outcomes = list(outcomes or [])
        self.figures = figures or {}
        self.sources: list[str] = []
        self.started, self.stopped = [], []
        self.index = 0

    async def start_kernel(self, hid, project_id, project_dir):
        self.started.append(hid)

    async def stop_kernel(self, hid):
        self.stopped.append(hid)

    async def run_cell(self, hid, source, timeout=600):
        cell = CodeCell(hypothesis_id=hid, index=self.index, source=source)
        self.index += 1
        self.sources.append(source)
        if "__SCRAP_DESIGN__" in source:
            cell.status, cell.stdout = CellStatus.ok, "__SCRAP_DESIGN__" + json.dumps(DESIGN)
            return cell
        status = self.outcomes.pop(0) if self.outcomes else CellStatus.ok
        cell.status = status
        cell.stdout = "padj 0.01" if status == CellStatus.ok else ""
        cell.stderr = "" if status == CellStatus.ok else "KeyError: 'pvalue'"
        cell.figure_paths = self.figures.get(cell.index, [])
        return cell


def draft(p_adj=0.01, effect=1.7, figure_cell=None, claim="IFN up in monocytes") -> str:
    return DraftFinding(claim=claim, test="pseudobulk DESeq2", statistic=3.3, p_adj=p_adj,
                        effect_size=effect, figure_cell=figure_cell).model_dump_json()


def review(verdict="approve", issues=(), fix="") -> str:
    return Review(verdict=verdict, issues=list(issues), fix=fix).model_dump_json()


@pytest.fixture
def setup(monkeypatch, fake_llm, events, brief, summary, tmp_path):
    kernel = FakeKernel()
    for name in ("start_kernel", "stop_kernel", "run_cell"):
        monkeypatch.setattr(km, name, getattr(kernel, name))
    monkeypatch.setattr(hyp, "chat", fake_llm)
    novelty_calls = []

    async def fake_novelty(project_id, project_dir, prefix, finding, online=False):
        novelty_calls.append(finding.id)
    monkeypatch.setattr(literature, "novelty", fake_novelty)
    ctx = RunContext("p1", tmp_path, brief, summary, "PREFIX")
    fake_llm.reply("coder", CODE).reply("reader", "Looks significant.")
    h = Hypothesis(project_id="p1", title="IFN is up", plan_steps=["pseudobulk", "test"])
    return type("S", (), dict(kernel=kernel, llm=fake_llm, events=events, ctx=ctx, h=h,
                              novelty_calls=novelty_calls))


def statuses(events) -> list[str]:
    out = []
    for e in events:
        if e.type == "hypothesis_status" and (not out or out[-1] != e.payload["status"]):
            out.append(e.payload["status"])
    return out


# --- happy path ---

async def test_approved_finding_end_to_end(setup):
    setup.llm.reply("finding", draft()).reply("critic", review())
    f = await hyp.run_hypothesis(setup.ctx, setup.h)
    assert f.critic_verdict == "approve" and f.p_adj == 0.01 and f.effect_size == 1.7
    assert f.notebook_path == str(Path(setup.ctx.project_dir) / "hypotheses" / setup.h.id / f"{setup.h.id}.ipynb")
    assert statuses(setup.events) == ["coding", "running", "coding", "running", "critiquing", "approved"]
    assert [e.type for e in setup.events].count("finding") == 1
    assert setup.kernel.started == setup.kernel.stopped == [setup.h.id]
    assert setup.novelty_calls == [f.id]
    assert len(setup.llm.by_agent("coder")) == 2 and len(setup.llm.by_agent("reader")) == 2


async def test_code_is_extracted_from_the_markdown_block(setup):
    setup.llm.reply("finding", draft()).reply("critic", review())
    await hyp.run_hypothesis(setup.ctx, setup.h)
    assert setup.kernel.sources[0].startswith("counts, meta = pseudobulk")


async def test_figure_from_the_cell_the_finding_points_to(setup):
    setup.kernel.figures = {0: ["/f/cell0.png"], 1: ["/f/cell1.png"]}
    setup.llm.reply("finding", draft(figure_cell=0)).reply("critic", review())
    assert (await hyp.run_hypothesis(setup.ctx, setup.h)).figure_path == "/f/cell0.png"


async def test_figure_falls_back_to_last_plot(setup):
    setup.kernel.figures = {0: ["/f/cell0.png"], 1: ["/f/cell1.png"]}
    setup.llm.reply("finding", draft(figure_cell=None)).reply("critic", review())
    assert (await hyp.run_hypothesis(setup.ctx, setup.h)).figure_path == "/f/cell1.png"


# --- retries ---

async def test_coder_retries_with_the_error_and_links_calls(setup):
    setup.kernel.outcomes = [CellStatus.error, CellStatus.ok, CellStatus.ok]
    setup.llm.reply("finding", draft()).reply("critic", review())
    f = await hyp.run_hypothesis(setup.ctx, setup.h)
    coder = setup.llm.by_agent("coder")
    assert f.critic_verdict == "approve" and len(coder) == 3
    retry_prompt = coder[1]["messages"][1]["content"]
    assert "Your previous attempt failed" in retry_prompt and "KeyError: 'pvalue'" in retry_prompt
    assert coder[1]["kwargs"]["parent_call_id"] == coder[0]["call"].id


async def test_step_fails_after_max_attempts(setup):
    setup.kernel.outcomes = [CellStatus.error] * (hyp.MAX_FIX_ATTEMPTS + 1)
    f = await hyp.run_hypothesis(setup.ctx, setup.h)
    assert f is None and statuses(setup.events)[-1] == "failed"
    assert len(setup.llm.by_agent("coder")) == hyp.MAX_FIX_ATTEMPTS + 1
    assert setup.kernel.stopped == [setup.h.id]
    assert not setup.llm.by_agent("critic")


async def test_coder_prompt_puts_the_current_step_last(setup):
    """Stable text first so vLLM can reuse cached blocks across steps."""
    setup.llm.reply("finding", draft()).reply("critic", review())
    await hyp.run_hypothesis(setup.ctx, setup.h)
    second = setup.llm.by_agent("coder")[1]["messages"][1]["content"]
    assert second.rstrip().endswith("Current step: test")
    assert second.index("Previous cells:") < second.index("Current step:")


# --- critic ---

async def test_critic_revision_adds_a_cell_then_approves(setup):
    setup.llm.reply("finding", draft(), draft())
    setup.llm.reply("critic", review("revise", ["no effect size"], "print cohens_d"), review("approve"))
    f = await hyp.run_hypothesis(setup.ctx, setup.h)
    assert f.critic_verdict == "approve"
    assert "Round 1: revise" in f.critic_notes and "print cohens_d" in f.critic_notes
    assert len(setup.llm.by_agent("coder")) == 3
    assert "Statistics critic requested: print cohens_d" in setup.llm.by_agent("coder")[2]["messages"][1]["content"]


async def test_unresolved_revision_is_a_reject(setup):
    setup.llm.reply("finding", draft()).reply("critic", review("revise", ["x"], "do y"))
    f = await hyp.run_hypothesis(setup.ctx, setup.h)
    assert f.critic_verdict == "reject" and statuses(setup.events)[-1] == "rejected"
    assert len(setup.llm.by_agent("critic")) == hyp.MAX_REVISIONS + 1
    assert setup.novelty_calls == []


async def test_critic_reject(setup):
    setup.llm.reply("finding", draft()).reply("critic", review("reject", ["numbers do not support it"]))
    f = await hyp.run_hypothesis(setup.ctx, setup.h)
    assert f.critic_verdict == "reject" and "numbers do not support it" in f.critic_notes


async def test_critic_gets_a_fresh_context(setup):
    setup.llm.reply("reader", "SECRET READER NOTE").reply("finding", draft()).reply("critic", review())
    setup.h.rationale = "SECRET RATIONALE"
    await hyp.run_hypothesis(setup.ctx, setup.h)
    critic_prompt = setup.llm.by_agent("critic")[0]["messages"][1]["content"]
    assert "SECRET READER NOTE" not in critic_prompt and "SECRET RATIONALE" not in critic_prompt
    assert "Automated checks:" in critic_prompt and "[PASS] pseudobulk" in critic_prompt


async def test_non_significant_finding_is_rejected_even_if_critic_approves(setup):
    setup.llm.reply("finding", draft(p_adj=0.078)).reply("critic", review("approve"))
    f = await hyp.run_hypothesis(setup.ctx, setup.h)
    assert f.critic_verdict == "reject" and "Overridden to reject" in f.critic_notes
    assert statuses(setup.events)[-1] == "rejected"


async def test_critic_off_approves_without_checks(setup):
    setup.llm.reply("finding", draft(p_adj=0.2))
    f = await hyp.run_hypothesis(setup.ctx, setup.h, critic=False)
    assert f.critic_verdict == "approve" and "Critic disabled" in f.critic_notes
    assert not setup.llm.by_agent("critic")
    assert not any("__SCRAP_DESIGN__" in s for s in setup.kernel.sources)


# --- robustness ---

async def test_novelty_failure_does_not_lose_the_finding(setup, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("index broken")
    monkeypatch.setattr(literature, "novelty", boom)
    setup.llm.reply("finding", draft()).reply("critic", review())
    f = await hyp.run_hypothesis(setup.ctx, setup.h)
    assert f.critic_verdict == "approve" and [e.type for e in setup.events].count("finding") == 1


async def test_exception_marks_failed_and_stops_kernel(setup):
    def vllm_down(messages, kwargs):
        raise RuntimeError("vLLM down")
    setup.llm.script["reader"] = [vllm_down]
    with pytest.raises(RuntimeError, match="vLLM down"):
        await hyp.run_hypothesis(setup.ctx, setup.h)
    assert statuses(setup.events)[-1] == "failed" and setup.kernel.stopped == [setup.h.id]


# --- planner ---

def plan_json(n=3, steps=("a", "b")) -> str:
    return Plan(hypotheses=[PlannedHypothesis(title=f"H{i}", rationale="r", plan_steps=list(steps))
                            for i in range(n)]).model_dump_json()


async def test_plan_hypotheses(setup):
    setup.llm.reply("planner", plan_json(4))
    hs = await hyp.plan_hypotheses(setup.ctx, n=3, background="BG TEXT",
                                   past=[Hypothesis(project_id="p1", title="OLD", status="rejected")])
    assert [h.title for h in hs] == ["H0", "H1", "H2"]
    assert all(h.project_id == "p1" and h.status == "planning" for h in hs)
    call = setup.llm.by_agent("planner")[0]
    assert call["kwargs"]["schema"] is Plan
    assert "BG TEXT" in call["messages"][1]["content"] and "OLD (rejected)" in call["messages"][1]["content"]
    assert "Propose 3 hypotheses" in call["messages"][0]["content"]


def test_plan_schema_limits_steps_to_2_to_4():
    schema = PlannedHypothesis.model_json_schema()["properties"]["plan_steps"]
    assert (schema["minItems"], schema["maxItems"]) == (2, 4)
    with pytest.raises(ValidationError):
        PlannedHypothesis(title="t", rationale="r", plan_steps=["a"] * 8)


@pytest.mark.parametrize("text, code", [
    ("```python\nx = 1\n```", "x = 1"),
    ("think\n```\ny = 2\n```", "y = 2"),
    ("```python\na\n```\nthen\n```python\nb\n```", "b"),
    ("plain code", "plain code"),
])
def test_extract_code(text, code):
    assert hyp._extract_code(text) == code


def test_show_cell_clips_long_output():
    c = CodeCell(hypothesis_id="h", index=3, source="x", stdout="a" * 10_000, stderr="err")
    shown = hyp._show_cell(c)
    assert shown.startswith("[cell 3]") and "[stderr]\nerr" in shown
    assert len(shown) < hyp.CONTEXT_CHARS * 2 + 200


def test_run_context_load(tmp_path, brief, summary):
    (tmp_path / "dataset_summary.json").write_text(json.dumps(summary))
    ctx = RunContext.load("p1", tmp_path, brief)
    assert ctx.summary["n_cells"] == 1000 and "`disease`" in ctx.prefix


# --- analysis.json for the project page ---

def analysis(setup) -> dict:
    return json.loads((Path(setup.ctx.project_dir) / "hypotheses" / setup.h.id / "analysis.json").read_text())


async def test_analysis_record_after_critic_approval(setup):
    """Regression: a local named `results` once shadowed the results module, so this file was silently lost."""
    setup.llm.reply("reader", "Monocytes score higher.").reply("finding", draft()).reply("critic", review())
    await hyp.run_hypothesis(setup.ctx, setup.h)
    a = analysis(setup)
    assert [s["step"] for s in a["steps"]] == ["pseudobulk", "test"]
    assert a["steps"][0]["interpretation"] == "Looks significant."
    assert a["steps"][1]["interpretation"] == "Monocytes score higher."
    assert a["finding"]["critic_verdict"] == "approve" and a["hypothesis"]["status"] == "approved"
    assert not any("__SCRAP_DESIGN__" in s["cell"]["source"] for s in a["steps"])


async def test_analysis_record_includes_critic_revision_step(setup):
    setup.llm.reply("finding", draft(), draft())
    setup.llm.reply("critic", review("revise", ["x"], "print cohens_d"), review("approve"))
    await hyp.run_hypothesis(setup.ctx, setup.h)
    assert analysis(setup)["steps"][-1]["step"] == "Statistics critic requested: print cohens_d"


async def test_analysis_record_for_a_failed_step(setup):
    setup.kernel.outcomes = [CellStatus.error] * (hyp.MAX_FIX_ATTEMPTS + 1)
    await hyp.run_hypothesis(setup.ctx, setup.h)
    a = analysis(setup)
    assert a["finding"] is None and a["hypothesis"]["status"] == "failed"
    assert a["steps"][0]["cell"]["status"] == "error" and "failed after every retry" in a["steps"][0]["interpretation"]


async def test_analysis_record_survives_a_crash(setup):
    def vllm_down(messages, kwargs):
        raise RuntimeError("vLLM down")
    setup.llm.script["finding"] = [vllm_down]
    with pytest.raises(RuntimeError):
        await hyp.run_hypothesis(setup.ctx, setup.h)
    a = analysis(setup)
    assert len(a["steps"]) == 2 and a["finding"] is None


async def test_critic_off_findings_get_files_too(setup):
    setup.kernel.figures = {1: ["/f/cell1.png"]}
    setup.llm.reply("finding", draft())
    f = await hyp.run_hypothesis(setup.ctx, setup.h, critic=False)
    assert f.figure_path == "/f/cell1.png" and f.notebook_path.endswith(f"{setup.h.id}.ipynb")
