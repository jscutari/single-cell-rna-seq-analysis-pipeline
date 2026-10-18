"""Benchmark suite: recovery of published findings on 7 datasets, plus a shuffled-label control.

    uv run python -m bench.suite [--datasets wilk,leng] [--variants multi,no_critic,single]
                                 [--repeats 2] [--hypotheses 5] [--out bench/results/suite.jsonl]
    uv run python -m bench.suite --report          # summary table from the results file only

Variants (same data, same brief, same model):
  multi      planner -> hypotheses in parallel -> reader -> critic + deterministic checks
  no_critic  the same planned hypotheses as `multi` in that repeat, critic and checks disabled
  single     one agent writing cells in a single conversation (bench/baseline_single_agent.py)

Datasets come from bench/datasets.json, preprocessed into $DATA_ROOT/_reference/<id>
(bench/prepare_datasets.py). `wilk_shuffled` has the condition labels permuted
across donors, so every accepted significant finding on it is a false positive.

A finding from the paper counts as recovered when an accepted claim with
p_adj < 0.05 matches its topic and direction (bench/datasets.json, built from
each paper's abstract). Every run is appended to the results file as one JSON
line, so the suite resumes where it stopped.
"""

import argparse
import asyncio
import json
import os
import re
import shutil
import statistics
import time
from pathlib import Path

from agents.hypothesis import RunContext, plan_hypotheses, run_hypothesis
from bench.baseline_single_agent import run_baseline
from bench.covid_recovery import Tally, peak_running, vllm_metrics
from shared.events import set_sink
from shared.schemas import Brief, Finding, Hypothesis

DATA_ROOT = Path(os.environ.get("DATA_ROOT", "/home/ubuntu/workspace/data"))
REGISTRY = json.loads((Path(__file__).parent / "datasets.json").read_text())
RESULTS = Path(__file__).parent / "results"
CONTROL = "normal"
SHUFFLED = {"wilk_shuffled": "wilk"}  # negative control -> the dataset it was made from


def dataset_info(key: str) -> dict:
    return REGISTRY[SHUFFLED.get(key, key)]


def accepted(f: Finding) -> bool:
    return f.critic_verdict in (None, "approve") and f.p_adj is not None and f.p_adj < 0.05


def recovered(findings: list[Finding], rubric: list[dict]) -> list[str]:
    hits = []
    for item in rubric:
        topic, direction = item["topic"], item.get("direction")
        if any(accepted(f) and re.search(topic, f.claim, re.I) and (not direction or re.search(direction, f.claim, re.I))
               for f in findings):
            hits.append(item["name"])
    return hits


def make_project(key: str, run_id: str) -> Path:
    """A throwaway project folder of hard links to the reference data, so runs never mix files."""
    src, dst = DATA_ROOT / "_reference" / key, DATA_ROOT / "_bench" / run_id
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    for name in ("processed.h5ad", "dataset_summary.json", "umap_points.json"):
        if (src / name).exists():
            os.link(src / name, dst / name)
    return dst


def brief_for(key: str, summary: dict) -> Brief:
    info = dataset_info(key)
    labels = list(summary["obs_columns"]["disease"]["counts"])
    case = next(lab for lab in labels if lab != CONTROL)
    # Same neutral goal for every dataset: no hints about the paper's findings.
    goals = (f"Characterize how the {info['tissue']} differs between {case} and healthy (normal) donors: "
             "gene programs within cell types and shifts in cell-type composition.")
    return Brief(project_id=f"bench-{key}", organism="human", condition_column="disease",
                 condition_labels=[case, CONTROL], donor_column="donor_id", celltype_column="cell_type",
                 gene_id_format="symbol", goals=goals, online_search=False)


async def measured(coro, project_id: str, tally: Tally) -> tuple[list[Finding], dict]:
    before, start, stop, box = vllm_metrics(), time.perf_counter(), asyncio.Event(), {}
    watcher = asyncio.create_task(peak_running(stop, box))
    try:
        findings = await coro
    finally:
        stop.set()
        await watcher
    wall = time.perf_counter() - start
    after = vllm_metrics()
    delta = {k: after.get(k, 0) - before.get(k, 0) for k in after}
    t = tally.d[project_id]
    latencies = sorted(tally.latencies.get(project_id, []))
    stats = {
        "wall_s": round(wall, 1), "llm_calls": int(t["llm_calls"]),
        "tokens_in": int(t["tokens_in"]), "tokens_out": int(t["tokens_out"]),
        "cells": int(t["cells"]), "cells_ok": int(t["cells_ok"]),
        "peak_concurrent_requests": int(box.get("peak", 0)),
        "gen_tokens_per_s": round(delta.get("vllm:generation_tokens_total", 0) / wall, 1),
        "prefix_cache_hit_pct": round(100 * delta.get("vllm:prompt_tokens_cached_total", 0)
                                      / max(delta.get("vllm:prompt_tokens_total", 1), 1), 1),
        "spec_accept_pct": round(100 * delta.get("vllm:spec_decode_num_accepted_tokens_total", 0)
                                 / max(delta.get("vllm:spec_decode_num_draft_tokens_total", 1), 1), 1),
        "llm_latency_p50_ms": latencies[len(latencies) // 2] if latencies else None,
        "llm_latency_p95_ms": latencies[int(len(latencies) * .95)] if latencies else None,
    }
    return findings, stats


class LatencyTally(Tally):
    def __init__(self):
        super().__init__()
        self.latencies: dict[str, list[int]] = {}

    def __call__(self, e) -> None:
        super().__call__(e)
        if e.type == "llm_call":
            self.latencies.setdefault(e.project_id, []).append(e.payload["latency_ms"])


async def one_repeat(key: str, repeat: int, variants: list[str], n_hyp: int, done: set, out: Path,
                     tally: LatencyTally) -> None:
    summary = json.loads((DATA_ROOT / "_reference" / key / "dataset_summary.json").read_text())
    brief = brief_for(key, summary)
    rubric = dataset_info(key)["findings"] if key not in SHUFFLED else []
    planned: list[Hypothesis] | None = None

    def ctx_for(variant: str) -> RunContext:
        run_id = f"{key}-{variant}-r{repeat}"
        return RunContext.load(run_id, make_project(key, run_id), brief.model_copy(update={"project_id": run_id}))

    for variant in variants:
        if (key, variant, repeat) in done:
            continue
        ctx = ctx_for(variant)
        print(f"== {key} {variant} repeat {repeat}", flush=True)

        async def run() -> list[Finding]:
            nonlocal planned
            if variant == "single":
                return await run_baseline(ctx, f"{ctx.project_id}-agent")
            if variant == "multi" or planned is None:
                hs = await plan_hypotheses(ctx, n_hyp)
                planned = hs if variant == "multi" else planned
            else:  # no_critic reuses the hypotheses `multi` planned in this repeat
                hs = [Hypothesis(project_id=ctx.project_id, title=h.title, rationale=h.rationale,
                                 plan_steps=h.plan_steps) for h in planned]
            rs = await asyncio.gather(*(run_hypothesis(ctx, h, critic=(variant == "multi")) for h in hs),
                                      return_exceptions=True)
            return [r for r in rs if isinstance(r, Finding)]

        try:
            findings, stats = await measured(run(), ctx.project_id, tally)
            error = None
        except Exception as exc:  # one broken run must not stop the night's suite
            findings, stats, error = [], {}, f"{type(exc).__name__}: {exc}"
        row = {
            "dataset": key, "variant": variant, "repeat": repeat, "error": error,
            "n_findings": len(findings), "accepted_significant": sum(accepted(f) for f in findings),
            "rejected_by_critic": sum(f.critic_verdict == "reject" for f in findings),
            "recovered": recovered(findings, rubric), "rubric_size": len(rubric),
            "claims": [{"claim": f.claim, "test": f.test, "p_adj": f.p_adj, "effect_size": f.effect_size,
                        "verdict": f.critic_verdict} for f in findings],
            **stats,
        }
        with out.open("a") as fh:
            fh.write(json.dumps(row) + "\n")
        print(f"   recovered {len(row['recovered'])}/{len(rubric)}  accepted {row['accepted_significant']}"
              f"  rejected {row['rejected_by_critic']}  {stats.get('wall_s')}s  {error or ''}", flush=True)
        if variant != "multi":  # keep the full system's runs for inspection; drop the rest
            shutil.rmtree(DATA_ROOT / "_bench" / ctx.project_id, ignore_errors=True)


def load(out: Path) -> list[dict]:
    return [json.loads(line) for line in out.read_text().splitlines() if line.strip()] if out.exists() else []


def report(rows: list[dict]) -> str:
    """Markdown summary: recovery per dataset and variant, the negative control, and efficiency."""
    def mean(xs):
        xs = [x for x in xs if x is not None]
        return statistics.mean(xs) if xs else None

    def fmt(x, digits=1):
        return "–" if x is None else f"{x:.{digits}f}"

    ok = [r for r in rows if not r.get("error")]
    variants = [v for v in ("multi", "no_critic", "single") if any(r["variant"] == v for r in ok)]
    datasets = list(dict.fromkeys(r["dataset"] for r in ok))
    lines = ["## Recovery of published findings (mean over repeats)", "",
             "| Dataset | Findings in paper | " + " | ".join(variants) + " |",
             "| --- | --- |" + " --- |" * len(variants)]
    total = {v: [0.0, 0] for v in variants}
    for d in datasets:
        if d in SHUFFLED:
            continue
        size = dataset_info(d)["findings"]
        cells = []
        for v in variants:
            rs = [r for r in ok if r["dataset"] == d and r["variant"] == v]
            rec = mean([len(r["recovered"]) for r in rs])
            cells.append(f"{fmt(rec)} / {len(size)} (n={len(rs)})" if rs else "–")
            if rs:
                total[v][0] += rec
                total[v][1] += len(size)
        lines.append(f"| {dataset_info(d)['name']} | {len(size)} | " + " | ".join(cells) + " |")
    lines.append("| **All datasets** | | " + " | ".join(
        f"**{fmt(100 * t / n, 0)}%**" if n else "–" for t, n in total.values()) + " |")

    shuffled = [r for r in ok if r["dataset"] in SHUFFLED]
    if shuffled:
        lines += ["", "## Negative control: shuffled condition labels (no real difference exists)", "",
                  "| Variant | Runs | Hypotheses tested | Accepted (false positives) | Rejected by critic |",
                  "| --- | --- | --- | --- | --- |"]
        for v in variants:
            rs = [r for r in shuffled if r["variant"] == v]
            if rs:
                lines.append(f"| {v} | {len(rs)} | {sum(r['n_findings'] for r in rs)} | "
                             f"**{sum(r['accepted_significant'] for r in rs)}** | {sum(r['rejected_by_critic'] for r in rs)} |")

    lines += ["", "## Execution and efficiency (mean per run, all datasets)", "",
              "| Metric | " + " | ".join(variants) + " |", "| --- |" + " --- |" * len(variants)]
    metrics = [("Wall-clock (s)", "wall_s", 0), ("LLM calls", "llm_calls", 0), ("Code cells", "cells", 0),
               ("Cells that ran (%)", None, 0), ("Generated tokens/s", "gen_tokens_per_s", 0),
               ("Peak concurrent requests", "peak_concurrent_requests", 1),
               ("LLM latency p50 (s)", "llm_latency_p50_ms", 1), ("Accepted findings", "accepted_significant", 1)]
    for label, key, digits in metrics:
        vals = []
        for v in variants:
            rs = [r for r in ok if r["variant"] == v and r["dataset"] not in SHUFFLED]
            if key is None:
                x = mean([100 * r["cells_ok"] / r["cells"] for r in rs if r.get("cells")])
            elif key == "llm_latency_p50_ms":
                x = mean([r[key] / 1000 for r in rs if r.get(key)])
            else:
                x = mean([r.get(key) for r in rs])
            vals.append(fmt(x, digits))
        lines.append(f"| {label} | " + " | ".join(vals) + " |")
    errors = [r for r in rows if r.get("error")]
    if errors:
        lines += ["", f"{len(errors)} run(s) failed: " + "; ".join(f"{r['dataset']}/{r['variant']}/r{r['repeat']}: {r['error'][:80]}" for r in errors)]
    return "\n".join(lines) + "\n"


async def main(args) -> None:
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if args.report:
        text = report(load(out))
        (out.with_suffix(".md")).write_text(text)
        print(text)
        return
    tally = LatencyTally()
    set_sink(tally)
    done = {(r["dataset"], r["variant"], r["repeat"]) for r in load(out) if not r.get("error")}
    datasets = args.datasets.split(",") if args.datasets else list(REGISTRY) + list(SHUFFLED)
    variants = args.variants.split(",")
    for repeat in range(1, args.repeats + 1):
        for key in datasets:
            if not (DATA_ROOT / "_reference" / key / "dataset_summary.json").exists():
                print(f"!! {key}: not prepared yet, skipping", flush=True)
                continue
            await one_repeat(key, repeat, variants, args.hypotheses, done, out, tally)
    text = report(load(out))
    out.with_suffix(".md").write_text(text)
    print(text)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--datasets", default="")
    p.add_argument("--variants", default="multi,no_critic,single")
    p.add_argument("--repeats", type=int, default=2)
    p.add_argument("--hypotheses", type=int, default=5)
    p.add_argument("--out", default=str(RESULTS / "suite.jsonl"))
    p.add_argument("--report", action="store_true")
    asyncio.run(main(p.parse_args()))
