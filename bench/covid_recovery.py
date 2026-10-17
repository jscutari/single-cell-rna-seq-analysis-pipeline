"""COVID PBMC benchmark (Wilk et al. 2020): multi-agent vs critic off vs single agent.

    uv run python -m bench.covid_recovery [n_hypotheses]

Variants, run one after another so wall-clock times are comparable:
  multi      planner -> N hypotheses in parallel -> reader -> critic + checks
  no_critic  the same N planned hypotheses, critic and checks disabled
  baseline   one agent, same data and helpers, one conversation (bench/baseline_single_agent.py)

"Recovered" uses fixed keyword rules on each reported claim (transparent, no LLM
judge): a paper finding counts if an accepted, significant claim mentions it in
the right direction. Results go to bench/results/.
"""

import asyncio
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

import httpx

from agents.hypothesis import RunContext, plan_hypotheses, run_hypothesis
from agents import literature
from bench.baseline_single_agent import run_baseline
from shared.events import Event, EventType, set_sink
from shared.schemas import Brief, Finding, Hypothesis

DATA = Path("/home/ubuntu/workspace/data/covid_pbmc")
RESULTS = Path(__file__).parent / "results"
GOALS = ("Characterize how the peripheral immune response differs between hospitalized COVID-19 "
         "patients and healthy donors: gene programs within cell types and shifts in cell-type composition.")

# Wilk et al. 2020 findings: (topic pattern, direction pattern)
PAPER = {
    "ISG signature up": (r"interferon|\bISG|IFI27|ISG15|\bIFN", r"higher|increas|\bup|elevat|enrich|induc"),
    "HLA class II down": (r"HLA[- ]?(class[- ])?II|HLA-D[RPQ]|MHC[- ]?(class[- ])?II|CD74", r"lower|decreas|down|reduc"),
    "developing neutrophils": (r"neutrophil|granulocyte", r"develop|immature|progenitor|precursor|emerg|increas|expan|higher"),
}


def recovered(findings: list[Finding]) -> list[str]:
    ok = [f for f in findings if f.critic_verdict in (None, "approve") and f.p_adj is not None and f.p_adj < 0.05]
    return [name for name, (topic, direction) in PAPER.items()
            if any(re.search(topic, f.claim, re.I) and re.search(direction, f.claim, re.I) for f in ok)]


class Tally:
    """Collects events per variant (project_id)."""

    def __init__(self):
        self.d = defaultdict(lambda: defaultdict(float))

    def __call__(self, e: Event) -> None:
        v, p = self.d[e.project_id], e.payload
        if e.type == EventType.llm_call:
            v["llm_calls"] += 1
            v["tokens_in"] += p["tokens_in"]
            v["tokens_out"] += p["tokens_out"]
        elif e.type == EventType.cell_finished:
            v["cells"] += 1
            v["cells_ok"] += p["status"] == "ok"


def vllm_metrics() -> dict[str, float]:
    keep = ("vllm:prompt_tokens_total", "vllm:prompt_tokens_cached_total",
            "vllm:spec_decode_num_draft_tokens_total", "vllm:spec_decode_num_accepted_tokens_total",
            "vllm:generation_tokens_total")
    out = {}
    for line in httpx.get("http://localhost:8000/metrics").text.splitlines():
        name = line.split("{")[0]
        if name in keep:
            out[name] = float(line.split()[-1])
    return out


async def peak_running(stop: asyncio.Event, box: dict) -> None:
    async with httpx.AsyncClient() as client:
        while not stop.is_set():
            for line in (await client.get("http://localhost:8000/metrics")).text.splitlines():
                if line.startswith("vllm:num_requests_running{"):
                    box["peak"] = max(box.get("peak", 0), float(line.split()[-1]))
            await asyncio.sleep(0.5)


async def timed(name: str, coro, rows: dict, tally: Tally) -> list[Finding]:
    before, start, stop, box = vllm_metrics(), time.perf_counter(), asyncio.Event(), {}
    watcher = asyncio.create_task(peak_running(stop, box))
    findings = await coro
    stop.set()
    await watcher
    after = vllm_metrics()
    t = tally.d[f"bench-{name}"]
    delta = {k: after.get(k, 0) - before.get(k, 0) for k in after}
    rows[name] = {
        "wall_s": round(time.perf_counter() - start, 1),
        "llm_calls": int(t["llm_calls"]), "tokens_in": int(t["tokens_in"]), "tokens_out": int(t["tokens_out"]),
        "cells": int(t["cells"]), "cells_ok_pct": round(100 * t["cells_ok"] / max(t["cells"], 1)),
        "findings": len(findings),
        "accepted_significant": sum(1 for f in findings if f.critic_verdict in (None, "approve")
                                    and f.p_adj is not None and f.p_adj < 0.05),
        "accepted": sum(1 for f in findings if f.critic_verdict in (None, "approve")),
        "rejected_by_critic": sum(1 for f in findings if f.critic_verdict == "reject"),
        "revised_by_critic": sum(1 for f in findings if "Round 1: revise" in (f.critic_notes or "")),
        "recovered": recovered(findings),
        "peak_concurrent_requests": int(box.get("peak", 0)),
        "prefix_cache_hit_pct": round(100 * delta.get("vllm:prompt_tokens_cached_total", 0)
                                      / max(delta.get("vllm:prompt_tokens_total", 1), 1), 1),
        "spec_decode_accept_pct": round(100 * delta.get("vllm:spec_decode_num_accepted_tokens_total", 0)
                                        / max(delta.get("vllm:spec_decode_num_draft_tokens_total", 1), 1), 1),
        "gen_tokens_per_s": round(delta.get("vllm:generation_tokens_total", 0) / (time.perf_counter() - start), 1),
        "claims": [{"claim": f.claim, "p_adj": f.p_adj, "effect_size": f.effect_size,
                    "verdict": f.critic_verdict} for f in findings],
    }
    print(f"\n== {name}: {json.dumps({k: v for k, v in rows[name].items() if k != 'claims'})}", flush=True)
    return findings


def ctx_for(variant: str) -> RunContext:
    brief = Brief(project_id=f"bench-{variant}", organism="human", condition_column="disease",
                  condition_labels=["COVID-19", "normal"], donor_column="donor_id",
                  celltype_column="cell.type.fine", gene_id_format="symbol", goals=GOALS)
    return RunContext.load(f"bench-{variant}", DATA, brief)


def copy_for(h: Hypothesis, project_id: str) -> Hypothesis:
    return Hypothesis(project_id=project_id, title=h.title, rationale=h.rationale, plan_steps=h.plan_steps)


async def main(n: int) -> None:
    tally = Tally()
    set_sink(tally)
    rows: dict = {}

    multi, nocrit = ctx_for("multi"), ctx_for("no_critic")
    try:
        background, _ = await literature.background(multi.project_id, DATA, multi.prefix, GOALS)
    except Exception as exc:
        print("literature background skipped:", exc)
        background = ""

    async def multi_run():
        hs = await plan_hypotheses(multi, n, background)
        multi_run.hypotheses = hs
        rs = await asyncio.gather(*(run_hypothesis(multi, h) for h in hs), return_exceptions=True)
        return [r for r in rs if isinstance(r, Finding)]

    async def no_critic_run():
        hs = [copy_for(h, nocrit.project_id) for h in multi_run.hypotheses]
        rs = await asyncio.gather(*(run_hypothesis(nocrit, h, critic=False) for h in hs), return_exceptions=True)
        return [r for r in rs if isinstance(r, Finding)]

    await timed("multi", multi_run(), rows, tally)
    await timed("no_critic", no_critic_run(), rows, tally)
    await timed("baseline", run_baseline(ctx_for("baseline"), "bench-baseline-run"), rows, tally)

    RESULTS.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    (RESULTS / f"covid_{stamp}.json").write_text(json.dumps(
        {"n_hypotheses": n, "hypotheses": [h.title for h in multi_run.hypotheses], "rows": rows}, indent=2))
    table = markdown(rows, n)
    (RESULTS / "covid_latest.md").write_text(table)
    print("\n" + table)


def markdown(rows: dict, n: int) -> str:
    metrics = [("Paper findings recovered (of 3)", lambda r: f"{len(r['recovered'])}: {', '.join(r['recovered']) or '-'}"),
               ("Findings reported", lambda r: r["findings"]),
               ("Accepted and significant", lambda r: r["accepted_significant"]),
               ("Rejected by critic", lambda r: r["rejected_by_critic"]),
               ("Revised by critic", lambda r: r["revised_by_critic"]),
               ("Code cells run / % ok", lambda r: f"{r['cells']} / {r['cells_ok_pct']}%"),
               ("Wall-clock (s)", lambda r: r["wall_s"]),
               ("LLM calls", lambda r: r["llm_calls"]),
               ("Tokens in / out", lambda r: f"{r['tokens_in']:,} / {r['tokens_out']:,}"),
               ("Peak concurrent requests", lambda r: r["peak_concurrent_requests"]),
               ("Prefix-cache hit (% prompt tokens)", lambda r: r["prefix_cache_hit_pct"]),
               ("Speculative decoding acceptance (%)", lambda r: r["spec_decode_accept_pct"]),
               ("Generated tokens/s", lambda r: r["gen_tokens_per_s"])]
    cols = list(rows)
    out = [f"COVID PBMC (Wilk et al. 2020), {n} planned hypotheses\n",
           "| Metric | " + " | ".join(cols) + " |", "| --- |" + " --- |" * len(cols)]
    out += [f"| {name} | " + " | ".join(str(fn(rows[c])) for c in cols) + " |" for name, fn in metrics]
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 5))
