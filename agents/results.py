"""Everything an analysis produces, saved on disk for the app's project page.

Live progress goes out as events; this module keeps a durable picture the
backend can serve at any time (also after a restart):

  <project_dir>/project_state.json             one snapshot of the whole project
  <project_dir>/hypotheses/<id>/analysis.json  one per hypothesis: steps, cells,
                                               interpretations, finding, chart

project_state.json:
  project_id, stage, updated_at
  brief               Brief or null
  dataset             {n_cells, n_genes, chart}   chart = UMAP by cell type, or null
  background          cited literature summary ("" if none)
  sources_searched    source ids
  hypotheses          [{hypothesis: Hypothesis, analysis: analysis.json or null}]
  findings            [{finding: Finding, hypothesis_title, chart, figure, notebook}]
  report              final report Markdown, or null
  files               [{id, project_id, name, kind, size_bytes, path, added_at, summary}]

All paths are relative to the project folder. The backend turns `path` into a
URL (e.g. /api/projects/<id>/files/<path>). Charts use data units:
  volcano  {type, x_label, y_label, threshold, points: [[log2fc, -log10 padj]], labels: [{x, y, text}]}
  bar      {type, xLabel, bars: [{label, value, group}]}
  umap     {type, clusters: [{label, color, points: [[x, y]]}]}   (x, y scaled to 0-1)
"""

import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from shared.schemas import Brief, CodeCell, Finding, Hypothesis

PALETTE = ["#a4c7ed", "#e8adb1", "#c7d9a8", "#f2cf8f", "#c9b3e0", "#9ccfc9", "#9ca9b9",
           "#f0b98d", "#d9a3c4", "#b8c48f", "#8fb3d9", "#d4b89c"]
VOLCANO_POINTS = 2500
VOLCANO_LABELS = 8
_KIND = {"pdf": "pdf", "csv": "csv", "tsv": "tsv", "png": "image", "jpg": "image", "jpeg": "image",
         "svg": "image", "txt": "text", "md": "text", "json": "text", "ipynb": "text", "h5ad": "h5ad"}


# --- per-hypothesis record ---

def save_analysis(project_dir: Path, h: Hypothesis, steps: list[tuple[str, CodeCell, str]],
                  finding: Finding | None) -> dict:
    """Write hypotheses/<id>/analysis.json: each step's code, output, figures and interpretation."""
    hdir = Path(project_dir) / "hypotheses" / h.id
    hdir.mkdir(parents=True, exist_ok=True)
    record = {
        "hypothesis": h.model_dump(mode="json"),
        "steps": [{"step": label, "interpretation": note, "cell": {
            "index": c.index, "source": c.source, "status": c.status, "stdout": c.stdout, "stderr": c.stderr,
            "figures": [_rel(project_dir, p) for p in c.figure_paths]}} for label, c, note in steps],
        "finding": finding.model_dump(mode="json") if finding else None,
        "chart": chart_for(hdir, finding) if finding else None,
    }
    _write_json(hdir / "analysis.json", record)
    return record


# --- charts ---

def chart_for(hypothesis_dir: Path, finding: Finding) -> dict | None:
    """Chart from the latest table the helpers saved: DESeq2 -> volcano, donor scores -> bar."""
    tables = Path(hypothesis_dir) / "tables"
    de, scores = _latest(tables, "de"), _latest(tables, "scores")
    prefer_de = "deseq" in (finding.test or "").lower()
    for path in ([de, scores] if prefer_de else [scores, de]):
        if path is not None:
            return volcano(path) if path.name.startswith("de_") else donor_bar(path)
    return None


def volcano(csv: Path) -> dict:
    import pandas as pd
    df = pd.read_csv(csv, index_col=0).dropna(subset=["log2FoldChange", "padj"])
    meta = _sidecar(csv)
    df["nlp"] = -np.log10(df["padj"].clip(lower=1e-300))
    top = df.sort_values("padj").head(VOLCANO_LABELS)
    # Keep every significant gene and a sample of the rest, so big tables stay small.
    sig = df[df["padj"] < 0.05]
    rest = df.drop(sig.index)
    keep = sig.head(VOLCANO_POINTS) if len(sig) >= VOLCANO_POINTS else \
        pd.concat([sig, rest.sample(min(len(rest), VOLCANO_POINTS - len(sig)), random_state=0)])
    return {
        "type": "volcano",
        "x_label": f"log2 fold change ({meta.get('case', 'case')} vs {meta.get('control', 'control')})",
        "y_label": "-log10 adjusted p",
        "threshold": round(-math.log10(0.05), 4),
        "points": [[round(float(a), 3), round(float(b), 3)] for a, b in zip(keep["log2FoldChange"], keep["nlp"])],
        "labels": [{"x": round(float(r.log2FoldChange), 3), "y": round(float(r.nlp), 3), "text": str(g)}
                   for g, r in top.iterrows()],
    }


def donor_bar(csv: Path) -> dict:
    import pandas as pd
    df = pd.read_csv(csv, index_col=0).sort_values(["condition", "score"])
    meta = _sidecar(csv)
    where = f" in {meta['celltype']}" if meta.get("celltype") else ""
    return {"type": "bar", "xLabel": f"Gene-set score per donor{where}",
            "bars": [{"label": str(d), "value": round(float(r.score), 4), "group": str(r.condition)}
                     for d, r in df.iterrows()]}


def umap_chart(project_dir: Path, label_column: str | None) -> dict | None:
    path = Path(project_dir) / "umap_points.json"
    if not path.exists():
        return None
    pts = json.loads(path.read_text())
    labels = pts["labels"].get(label_column) if label_column else None
    if labels is None:
        labels = ["cells"] * len(pts["x"])
    groups: dict[str, list] = {}
    for x, y, lab in zip(pts["x"], pts["y"], labels):
        groups.setdefault(lab, []).append([x, y])
    ordered = sorted(groups.items(), key=lambda kv: -len(kv[1]))
    return {"type": "umap", "clusters": [{"label": lab, "color": PALETTE[i % len(PALETTE)], "points": p}
                                         for i, (lab, p) in enumerate(ordered)]}


# --- files ---

def list_files(project_dir: Path, project_id: str, summary: dict | None, brief: Brief | None,
               titles: dict[str, str]) -> list[dict]:
    """Every file worth showing, in the app's ProjectFile shape (path instead of url)."""
    root = Path(project_dir)
    out = []

    def add(path: Path, summary_text: str | None = None) -> None:
        if path.is_file():
            st = path.stat()
            rel = _rel(root, path)
            out.append({"id": hashlib.sha1(f"{project_id}/{rel}".encode()).hexdigest()[:16],
                        "project_id": project_id, "name": path.name, "kind": _KIND.get(path.suffix[1:].lower(), "other"),
                        "size_bytes": st.st_size, "path": rel,
                        "added_at": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(),
                        "summary": summary_text})

    add(root / "dataset.h5ad", "Uploaded dataset")
    add(root / "processed.h5ad", _dataset_line(summary, brief))
    add(root / "umap_overview.png", "UMAP overview")
    for pdf in sorted((root / "sources").glob("*.pdf")):
        add(pdf, "Uploaded paper")
    add(root / "background.md", "Literature background")
    add(root / "report.md", "Final report")
    for hdir in sorted((root / "hypotheses").glob("*")):
        title = titles.get(hdir.name, hdir.name)
        add(hdir / f"{hdir.name}.ipynb", f"Notebook: {title}")
        for fig in sorted((hdir / "figures").glob("*.png")):
            add(fig, f"Figure (cell {int(fig.stem[4:7])}): {title}" if fig.stem.startswith("cell") else title)
        for csv in sorted((hdir / "tables").glob("*.csv")):
            what = "Differential expression (DESeq2)" if csv.name.startswith("de_") else "Donor-level scores"
            add(csv, f"{what}: {title}")
    return out


def _dataset_line(summary: dict | None, brief: Brief | None) -> str | None:
    if not summary:
        return None
    parts = [f"{summary['n_cells']:,} cells", f"{summary['n_genes']:,} genes"]
    cols = summary.get("obs_columns", {})
    if brief and brief.donor_column in cols:
        parts.append(f"{cols[brief.donor_column]['n_unique']} donors")
    if brief and brief.condition_column in cols and "counts" in cols[brief.condition_column]:
        parts.append(" / ".join(f"{k}" for k in cols[brief.condition_column]["counts"]))
    return " · ".join(parts)


# --- project snapshot ---

def write_state(project_dir: Path, project_id: str, stage: str, brief: Brief | None, summary: dict | None,
                background: str, sources: list[str], hypotheses: list[Hypothesis], report: str | None) -> dict:
    root = Path(project_dir)
    entries, findings = [], []
    for h in hypotheses:
        path = root / "hypotheses" / h.id / "analysis.json"
        analysis = json.loads(path.read_text()) if path.exists() else None
        entries.append({"hypothesis": h.model_dump(mode="json"), "analysis": analysis})
        if analysis and analysis.get("finding"):
            f = analysis["finding"]
            findings.append({"finding": f, "hypothesis_title": h.title, "chart": analysis.get("chart"),
                             "figure": _rel(root, f["figure_path"]) if f.get("figure_path") else None,
                             "notebook": _rel(root, f["notebook_path"]) if f.get("notebook_path") else None})
    state = {
        "project_id": project_id, "stage": stage, "updated_at": datetime.now(timezone.utc).isoformat(),
        "brief": brief.model_dump(mode="json") if brief else None,
        "dataset": {"n_cells": summary["n_cells"], "n_genes": summary["n_genes"],
                    "chart": umap_chart(root, brief.celltype_column if brief else None)} if summary else None,
        "background": background, "sources_searched": sources,
        "hypotheses": entries, "findings": findings, "report": report,
        "files": list_files(root, project_id, summary, brief, {h.id: h.title for h in hypotheses}),
    }
    _write_json(root / "project_state.json", state)
    return state


# --- helpers ---

def _latest(tables: Path, kind: str) -> Path | None:
    found = sorted(tables.glob(f"{kind}_*.csv"))
    return found[-1] if found else None


def _sidecar(csv: Path) -> dict:
    side = csv.with_suffix(".json")
    return json.loads(side.read_text()) if side.exists() else {}


def _rel(root: Path, path: str | Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(Path(root).resolve()))
    except ValueError:
        return str(path)


def _write_json(path: Path, data: dict) -> None:
    """Write atomically, so a reader never sees half a file."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, default=str))
    os.replace(tmp, path)
