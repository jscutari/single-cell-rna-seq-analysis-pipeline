"""Serving benchmark: how the system scales with parallel hypotheses on one GPU.

    uv run python -m bench.serving --label interactive [--n 1,2,4,8] [--dataset wilk]
    uv run python -m bench.serving --report

Runs the full system (critic on) with N hypotheses in parallel and records
throughput, wall time, concurrency and per-call latency. Restart vLLM between
labels to compare serving setups, e.g.:
    bash infra/serve_vllm.sh                      # label: interactive (DSpark speculative decoding)
    MODE=throughput bash infra/serve_vllm.sh      # label: throughput (no speculative decoding)
    NO_PREFIX_CACHE=1 bash infra/serve_vllm.sh    # label: no_prefix_cache
"""

import argparse
import asyncio
import json
import statistics
from pathlib import Path

from agents.hypothesis import RunContext, plan_hypotheses, run_hypothesis
from bench.suite import DATA_ROOT, LatencyTally, accepted, brief_for, load, make_project, measured
from shared.events import set_sink
from shared.schemas import Finding

OUT = Path(__file__).parent / "results" / "serving.jsonl"


async def one(label: str, dataset: str, n: int, tally: LatencyTally) -> dict:
    summary = json.loads((DATA_ROOT / "_reference" / dataset / "dataset_summary.json").read_text())
    run_id = f"serving-{label}-n{n}"
    brief = brief_for(dataset, summary).model_copy(update={"project_id": run_id})
    ctx = RunContext.load(run_id, make_project(dataset, run_id), brief)

    async def run() -> list[Finding]:
        hs = await plan_hypotheses(ctx, n)
        rs = await asyncio.gather(*(run_hypothesis(ctx, h) for h in hs), return_exceptions=True)
        return [r for r in rs if isinstance(r, Finding)]

    findings, stats = await measured(run(), run_id, tally)
    return {"label": label, "dataset": dataset, "n_hypotheses": n, "n_findings": len(findings),
            "accepted": sum(accepted(f) for f in findings), **stats}


def report(rows: list[dict]) -> str:
    lines = ["## Serving: parallel hypotheses on one H100", "",
             "| Setup | Parallel hypotheses | Wall (s) | Wall per hypothesis (s) | Generated tokens/s | Peak concurrent requests "
             "| LLM latency p50 / p95 (s) | Prefix cache hit (%) | Spec. decoding acceptance (%) | Accepted findings |",
             "| --- |" + " --- |" * 9]
    for r in sorted(rows, key=lambda r: (r["label"], r["n_hypotheses"])):
        p50, p95 = (r.get("llm_latency_p50_ms") or 0) / 1000, (r.get("llm_latency_p95_ms") or 0) / 1000
        lines.append(f"| {r['label']} | {r['n_hypotheses']} | {r['wall_s']:.0f} | {r['wall_s'] / r['n_hypotheses']:.0f} | "
                     f"{r['gen_tokens_per_s']:.0f} | {r['peak_concurrent_requests']} | {p50:.1f} / {p95:.1f} | "
                     f"{r['prefix_cache_hit_pct']} | {r['spec_accept_pct']} | {r['accepted']} / {r['n_findings']} |")
    labels = sorted({r["label"] for r in rows})
    if len(labels) > 1:
        lines += ["", "Mean generated tokens/s per setup: " + ", ".join(
            f"{lab} {statistics.mean(r['gen_tokens_per_s'] for r in rows if r['label'] == lab):.0f}" for lab in labels)]
    return "\n".join(lines) + "\n"


async def main(args) -> None:
    if args.report:
        text = report(load(OUT))
        OUT.with_suffix(".md").write_text(text)
        print(text)
        return
    tally = LatencyTally()
    set_sink(tally)
    done = {(r["label"], r["n_hypotheses"]) for r in load(OUT)}
    for n in [int(x) for x in args.n.split(",")]:
        if (args.label, n) in done:
            continue
        print(f"== {args.label}: {n} hypotheses in parallel", flush=True)
        row = await one(args.label, args.dataset, n, tally)
        with OUT.open("a") as fh:
            fh.write(json.dumps(row) + "\n")
        print(f"   {row['wall_s']}s, {row['gen_tokens_per_s']} tok/s, peak {row['peak_concurrent_requests']}", flush=True)
    text = report(load(OUT))
    OUT.with_suffix(".md").write_text(text)
    print(text)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--label", default="interactive")
    p.add_argument("--n", default="1,2,4,8")
    p.add_argument("--dataset", default="wilk")
    p.add_argument("--report", action="store_true")
    asyncio.run(main(p.parse_args()))
