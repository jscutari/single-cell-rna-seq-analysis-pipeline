"""agents/reporter.py, bench/baseline_single_agent.py and bench/covid_recovery.py scoring."""

import pytest

from agents import reporter
from bench import baseline_single_agent as baseline
from bench import covid_recovery as bench
from shared.schemas import Finding, Hypothesis


@pytest.fixture
def results():
    h1 = Hypothesis(project_id="p", title="IFN up", status="approved")
    h2 = Hypothesis(project_id="p", title="HLA down", status="rejected")
    h3 = Hypothesis(project_id="p", title="Neutrophils", status="failed")
    f1 = Finding(hypothesis_id=h1.id, claim="IFN is up", test="t", p_adj=0.01, effect_size=1.7,
                 critic_verdict="approve", novelty="known", citations=["wilk2020 p.3"])
    f2 = Finding(hypothesis_id=h2.id, claim="HLA unchanged", test="t", p_adj=0.2,
                 critic_verdict="reject", critic_notes="not significant")
    return [h1, h2, h3], [f1, f2]


def test_results_text_lists_every_hypothesis_with_its_evidence(results):
    text = reporter._results("BG", *results)
    assert "Background:\nBG" in text
    assert "1. IFN up [status: approved]" in text and "3. Neutrophils [status: failed]" in text
    assert "p_adj=0.01" in text and "novelty: known; citations: wilk2020 p.3" in text
    assert "critic: reject; not significant" in text


async def test_report_runs_without_reasoning(results, monkeypatch, fake_llm):
    monkeypatch.setattr(reporter, "chat", fake_llm.reply("reporter", "  # Report  "))
    assert await reporter.report("p", "PREFIX", "BG", *results) == "# Report"
    call = fake_llm.calls[0]
    assert call["kwargs"]["reasoning"] is False and "Markdown" in call["messages"][1]["content"]


async def test_answer_includes_recent_chat_and_question(results, monkeypatch, fake_llm):
    monkeypatch.setattr(reporter, "chat", fake_llm.reply("reporter", "Because..."))
    history = [("user", f"q{i}") for i in range(12)]
    assert await reporter.answer("p", "PREFIX", "BG", *results, history, "Why?") == "Because..."
    prompt = fake_llm.calls[0]["messages"][1]["content"]
    assert "Question: Why?\n" in prompt and "at most 200 words" in prompt
    assert "user: q11" in prompt and "user: q3" not in prompt


# --- benchmark scoring ---

def f(claim, p=0.01, verdict="approve"):
    return Finding(hypothesis_id="h", claim=claim, test="t", p_adj=p, critic_verdict=verdict)


def test_recovered_matches_topic_and_direction():
    found = bench.recovered([
        f("Hallmark interferon-alpha response is higher in CD14 monocytes"),
        f("HLA-DRA is lower in monocytes from COVID-19 patients"),
        f("Developing neutrophils emerge in ventilated patients"),
    ])
    assert found == ["ISG signature up", "HLA class II down", "developing neutrophils"]


@pytest.mark.parametrize("finding", [
    f("Interferon response is lower in COVID monocytes"),          # wrong direction
    f("Interferon response is higher", p=0.08),                     # not significant
    f("Interferon response is higher", p=None),                     # no statistics
    f("Interferon response is higher", verdict="reject"),           # critic rejected
])
def test_recovered_requires_direction_significance_and_acceptance(finding):
    assert bench.recovered([finding]) == []


def test_recovered_counts_unreviewed_baseline_claims_with_stats():
    assert bench.recovered([f("ISG15 is higher in COVID", verdict=None)]) == ["ISG signature up"]


def test_markdown_table_has_a_column_per_variant():
    row = {"recovered": ["ISG signature up"], "findings": 2, "accepted_significant": 1, "rejected_by_critic": 1,
           "revised_by_critic": 0, "cells": 10, "cells_ok_pct": 90, "wall_s": 12.0, "llm_calls": 5,
           "tokens_in": 1000, "tokens_out": 200, "peak_concurrent_requests": 3, "prefix_cache_hit_pct": 5.0,
           "spec_decode_accept_pct": 60.0, "gen_tokens_per_s": 500.0}
    table = bench.markdown({"multi": row, "baseline": row}, 5)
    assert "| Metric | multi | baseline |" in table
    assert "| Paper findings recovered (of 3) | 1: ISG signature up | 1: ISG signature up |" in table
    assert "| Tokens in / out | 1,000 / 200 | 1,000 / 200 |" in table


def test_tally_counts_calls_tokens_and_cells():
    from shared.events import Event
    t = bench.Tally()
    t(Event(type="llm_call", project_id="bench-multi", payload={"tokens_in": 10, "tokens_out": 5}))
    t(Event(type="cell_finished", project_id="bench-multi", payload={"status": "ok"}))
    t(Event(type="cell_finished", project_id="bench-multi", payload={"status": "error"}))
    v = t.d["bench-multi"]
    assert (v["llm_calls"], v["tokens_in"], v["cells"], v["cells_ok"]) == (1, 10, 2, 1)


# --- baseline parsing ---

def test_baseline_parses_final_json():
    text = 'Done.\nFINAL\n[{"claim": "IFN up", "test": "welch", "statistic": "3.1", "p_adj": 0.01, "effect_size": null}]'
    [finding] = baseline._parse_findings(text, "run")
    assert finding.claim == "IFN up" and finding.statistic == 3.1 and finding.effect_size is None
    assert finding.critic_verdict is None


@pytest.mark.parametrize("text", ["FINAL\nnot json", "FINAL\n[{broken", "no final at all", "FINAL\n[1, 2]"])
def test_baseline_bad_output_gives_no_findings(text):
    assert baseline._parse_findings(text, "run") == []


async def test_baseline_loop_runs_cells_until_final(monkeypatch, fake_llm, events, tmp_path, brief, summary):
    from agents.hypothesis import RunContext
    from sandbox import kernel_manager as km
    from shared.schemas import CodeCell

    ran = []

    async def run_cell(hid, source, timeout=600):
        ran.append(source)
        return CodeCell(hypothesis_id=hid, index=len(ran), source=source, status="ok", stdout="d = 1.7")

    async def noop(*a, **k):
        return None
    monkeypatch.setattr(km, "start_kernel", noop)
    monkeypatch.setattr(km, "stop_kernel", noop)
    monkeypatch.setattr(km, "run_cell", run_cell)
    fake_llm.reply("baseline", "```python\nx = 1\n```", "no code here",
                   'FINAL\n[{"claim": "IFN up", "test": "t", "statistic": 1, "p_adj": 0.01, "effect_size": 1.7}]')
    monkeypatch.setattr(baseline, "chat", fake_llm)
    findings = await baseline.run_baseline(RunContext("p", tmp_path, brief, summary, "PREFIX"))
    assert ran == ["x = 1"] and [x.claim for x in findings] == ["IFN up"]
    last = fake_llm.calls[-1]["messages"]
    assert "Output (ok):\nd = 1.7" in last[3]["content"]
    assert "Reply with one python code block" in last[5]["content"]
