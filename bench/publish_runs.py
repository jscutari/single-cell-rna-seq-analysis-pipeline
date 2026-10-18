"""Publish the benchmark's full-system runs as app projects, one per dataset.

    uv run python -m bench.publish_runs        # then restart the backend so it lists them

For each dataset, takes the `multi` run with the most approved findings from
$DATA_ROOT/_bench/, hard-links it into $DATA_ROOT/bench_<id>/ (no extra disk),
points the saved paths at the new folder, has the reporter write report.md,
and writes project_state.json and project.json. Existing projects are kept.
"""

import asyncio
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from agents import prompting, reporter, results
from bench.suite import DATA_ROOT, REGISTRY, brief_for
from shared.events import set_sink
from shared.schemas import Finding, Hypothesis, Project


def analyses(run: Path) -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(run.glob("hypotheses/*/analysis.json"))]


def approved(run: Path) -> int:
    return sum(1 for a in analyses(run) if (a.get("finding") or {}).get("critic_verdict") == "approve")


def relink_paths(folder: Path, old: Path) -> None:
    """Saved JSON holds absolute paths of the run folder; rewrite them (as new files, not through the links)."""
    for path in folder.rglob("*.json"):
        text = path.read_text()
        if str(old) in text:
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(text.replace(str(old), str(folder)))
            os.replace(tmp, path)


async def publish(key: str) -> str:
    runs = sorted((DATA_ROOT / "_bench").glob(f"{key}-multi-r*"))
    if not runs:
        return f"{key}: no multi run"
    src = max(runs, key=approved)
    pid = f"bench_{key}"
    dst = DATA_ROOT / pid
    if (dst / "project.json").exists():
        return f"{key}: {pid} already published"
    shutil.copytree(src, dst, copy_function=os.link, dirs_exist_ok=True)
    relink_paths(dst, src)
    raw = DATA_ROOT / "raw" / ("covid_pbmc_wilk2020.h5ad" if key == "wilk" else f"{key}.h5ad")
    if raw.exists() and not (dst / "dataset.h5ad").exists():
        os.link(raw, dst / "dataset.h5ad")

    summary = json.loads((dst / "dataset_summary.json").read_text())
    brief = brief_for(key, summary).model_copy(update={"project_id": pid})
    items = analyses(dst)
    hypotheses = [Hypothesis(**a["hypothesis"]) for a in items]
    findings = [Finding(**a["finding"]) for a in items if a.get("finding")]
    prefix = prompting.shared_prefix(summary, brief)
    report = await reporter.report(pid, prefix, "", hypotheses, findings)
    (dst / "report.md").write_text(report)
    results.write_state(dst, pid, "done", brief, summary, "", [], hypotheses, report)
    project = Project(id=pid, name=f"{REGISTRY[key]['name']}", dataset_path=str(dst / "dataset.h5ad"),
                      status="done", created_at=datetime.now(timezone.utc))
    (dst / "project.json").write_text(project.model_dump_json(indent=2))
    n_ok = sum(f.critic_verdict == "approve" for f in findings)
    return f"{key}: published {pid} from {src.name} ({len(hypotheses)} hypotheses, {n_ok} approved)"


async def main() -> None:
    set_sink(lambda e: None)
    for key in REGISTRY:
        print(await publish(key), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
