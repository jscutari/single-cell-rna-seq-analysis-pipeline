"""agents/results.py: what the project page reads (charts, files, analysis records, project_state.json)."""

import json

import numpy as np
import pandas as pd
import pytest

from agents import results
from shared.schemas import Brief, CodeCell, Finding, Hypothesis


def write_de(tables, n_genes=50, n_sig=5, name="de_01", case="COVID-19"):
    tables.mkdir(parents=True, exist_ok=True)
    padj = np.r_[np.logspace(-12, -3, n_sig), np.linspace(0.06, 1, n_genes - n_sig)]
    df = pd.DataFrame({"baseMean": 100.0, "log2FoldChange": np.linspace(3, -3, n_genes), "pvalue": padj / 2,
                       "padj": padj}, index=[f"G{i}" for i in range(n_genes)])
    df.to_csv(tables / f"{name}.csv")
    (tables / f"{name}.json").write_text(json.dumps({"case": case, "control": "normal"}))


def write_scores(tables, name="scores_01", celltype="CD14 Monocyte"):
    tables.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"condition": ["normal", "COVID-19", "COVID-19"], "n_cells": [50, 60, 70],
                  "score": [0.3, 0.7, 0.5]}, index=pd.Index(["H1", "C1", "C2"], name="donor")).to_csv(tables / f"{name}.csv")
    (tables / f"{name}.json").write_text(json.dumps({"n_genes": 97, "celltype": celltype}))


def finding(test="Welch t-test", **kw):
    return Finding(hypothesis_id="h", claim="c", test=test, p_adj=0.01, effect_size=1.0, **kw)


# --- charts ---

def test_volcano_uses_data_units_and_labels_top_genes(tmp_path):
    write_de(tmp_path / "tables")
    chart = results.volcano(tmp_path / "tables" / "de_01.csv")
    assert chart["type"] == "volcano" and chart["x_label"] == "log2 fold change (COVID-19 vs normal)"
    assert len(chart["points"]) == 50 and chart["threshold"] == pytest.approx(1.301, abs=1e-3)
    assert [lab["text"] for lab in chart["labels"]][:3] == ["G0", "G1", "G2"]
    assert chart["labels"][0] == {"x": 3.0, "y": 12.0, "text": "G0"}


def test_volcano_keeps_all_significant_genes_and_samples_the_rest(tmp_path):
    write_de(tmp_path / "tables", n_genes=6000, n_sig=100)
    chart = results.volcano(tmp_path / "tables" / "de_01.csv")
    assert len(chart["points"]) == results.VOLCANO_POINTS
    assert sum(1 for _, y in chart["points"] if y > chart["threshold"]) == 100


def test_donor_bar_groups_by_condition(tmp_path):
    write_scores(tmp_path / "tables")
    chart = results.donor_bar(tmp_path / "tables" / "scores_01.csv")
    assert chart["type"] == "bar" and chart["xLabel"] == "Gene-set score per donor in CD14 Monocyte"
    assert [b["label"] for b in chart["bars"]] == ["C2", "C1", "H1"]
    assert chart["bars"][1] == {"label": "C1", "value": 0.7, "group": "COVID-19"}


def test_chart_for_picks_the_table_matching_the_test(tmp_path):
    write_de(tmp_path / "tables")
    write_scores(tmp_path / "tables")
    assert results.chart_for(tmp_path, finding(test="pseudobulk DESeq2"))["type"] == "volcano"
    assert results.chart_for(tmp_path, finding(test="Welch t-test on donor scores"))["type"] == "bar"


def test_chart_for_uses_the_latest_table_and_falls_back(tmp_path):
    write_de(tmp_path / "tables", name="de_01", case="old")
    write_de(tmp_path / "tables", name="de_02", case="new")
    assert "new vs" in results.chart_for(tmp_path, finding())["x_label"]  # no scores table -> volcano
    assert results.chart_for(tmp_path / "empty", finding()) is None


def test_umap_chart_groups_by_the_cell_type_column(tmp_path):
    (tmp_path / "umap_points.json").write_text(json.dumps(
        {"x": [0.1, 0.2, 0.9], "y": [0.1, 0.3, 0.8], "labels": {"cell_type": ["NK", "Mono", "Mono"]}}))
    chart = results.umap_chart(tmp_path, "cell_type")
    assert [c["label"] for c in chart["clusters"]] == ["Mono", "NK"]
    assert chart["clusters"][0]["points"] == [[0.2, 0.3], [0.9, 0.8]] and chart["clusters"][0]["color"].startswith("#")
    assert [c["label"] for c in results.umap_chart(tmp_path, "unknown")["clusters"]] == ["cells"]
    assert results.umap_chart(tmp_path / "nope", "cell_type") is None


# --- files ---

def make_project(root):
    (root / "sources" / "index").mkdir(parents=True)
    (root / "sources" / "wilk2020.pdf").write_bytes(b"%PDF-1.4")
    (root / "sources" / "index" / "chunks.json").write_text("[]")
    for name in ("processed.h5ad", "umap_overview.png", "report.md", "background.md", "dataset.h5ad"):
        (root / name).write_bytes(b"x" * 10)
    h = root / "hypotheses" / "h1"
    (h / "figures").mkdir(parents=True)
    (h / "h1.ipynb").write_text("{}")
    (h / "figures" / "cell003_0.png").write_bytes(b"png")
    write_scores(h / "tables")


def test_list_files_inventory(tmp_path, summary, brief):
    make_project(tmp_path)
    files = results.list_files(tmp_path, "p1", summary, brief, {"h1": "IFN is up"})
    by_path = {f["path"]: f for f in files}
    assert set(by_path) == {"dataset.h5ad", "processed.h5ad", "umap_overview.png", "sources/wilk2020.pdf",
                            "background.md", "report.md", "hypotheses/h1/h1.ipynb",
                            "hypotheses/h1/figures/cell003_0.png", "hypotheses/h1/tables/scores_01.csv"}
    assert by_path["processed.h5ad"]["summary"] == "1,000 cells · 500 genes · 4 donors · COVID-19 / normal"
    assert by_path["hypotheses/h1/figures/cell003_0.png"]["summary"] == "Figure (cell 3): IFN is up"
    assert by_path["hypotheses/h1/figures/cell003_0.png"]["kind"] == "image"
    assert by_path["sources/wilk2020.pdf"]["kind"] == "pdf" and by_path["processed.h5ad"]["kind"] == "h5ad"
    assert by_path["hypotheses/h1/tables/scores_01.csv"]["summary"] == "Donor-level scores: IFN is up"
    f = by_path["report.md"]
    assert set(f) == {"id", "project_id", "name", "kind", "size_bytes", "path", "added_at", "summary"}
    assert f["size_bytes"] == 10 and f["added_at"].endswith("+00:00")
    again = results.list_files(tmp_path, "p1", summary, brief, {})
    assert {x["id"] for x in again} == {x["id"] for x in files}  # ids are stable


# --- analysis records and the project snapshot ---

def test_save_analysis_records_steps_interpretations_and_chart(tmp_path):
    h = Hypothesis(project_id="p1", title="IFN is up", plan_steps=["score", "test"])
    hdir = tmp_path / "hypotheses" / h.id
    write_scores(hdir / "tables")
    fig = hdir / "figures" / "cell001_0.png"
    cells = [CodeCell(hypothesis_id=h.id, index=0, source="a", status="ok", stdout="x"),
             CodeCell(hypothesis_id=h.id, index=1, source="b", status="ok", figure_paths=[str(fig)])]
    record = results.save_analysis(tmp_path, h, [("score", cells[0], "Scores look higher."),
                                                 ("test", cells[1], "d = 1.7")], finding())
    saved = json.loads((hdir / "analysis.json").read_text())
    assert saved == json.loads(json.dumps(record))
    assert [s["step"] for s in saved["steps"]] == ["score", "test"]
    assert saved["steps"][0]["interpretation"] == "Scores look higher."
    assert saved["steps"][1]["cell"]["figures"] == [f"hypotheses/{h.id}/figures/cell001_0.png"]
    assert saved["chart"]["type"] == "bar" and saved["finding"]["p_adj"] == 0.01


def test_save_analysis_without_finding(tmp_path):
    h = Hypothesis(project_id="p1", title="t")
    record = results.save_analysis(tmp_path, h, [], None)
    assert record["finding"] is None and record["chart"] is None


def test_write_state_collects_everything(tmp_path, summary, brief):
    (tmp_path / "umap_points.json").write_text(json.dumps(
        {"x": [0.1], "y": [0.2], "labels": {"cell.type.coarse": ["NK"]}}))
    h1 = Hypothesis(project_id="p1", title="IFN up", status="approved")
    h2 = Hypothesis(project_id="p1", title="Still running", status="coding")
    f = finding(figure_path=str(tmp_path / "hypotheses" / h1.id / "figures" / "cell001_0.png"),
                notebook_path=str(tmp_path / "hypotheses" / h1.id / f"{h1.id}.ipynb"), critic_verdict="approve")
    results.save_analysis(tmp_path, h1, [], f)
    state = results.write_state(tmp_path, "p1", "analysis", brief, summary, "BG [wilk2020 p.1]",
                                ["wilk2020"], [h1, h2], None)
    on_disk = json.loads((tmp_path / "project_state.json").read_text())
    assert on_disk == json.loads(json.dumps(state))
    assert on_disk["stage"] == "analysis" and on_disk["brief"]["condition_column"] == "disease"
    assert on_disk["dataset"]["n_cells"] == 1000 and on_disk["dataset"]["chart"]["clusters"][0]["label"] == "NK"
    assert [e["hypothesis"]["status"] for e in on_disk["hypotheses"]] == ["approved", "coding"]
    assert on_disk["hypotheses"][1]["analysis"] is None
    [card] = on_disk["findings"]
    assert card["hypothesis_title"] == "IFN up" and card["finding"]["critic_verdict"] == "approve"
    assert card["figure"] == f"hypotheses/{h1.id}/figures/cell001_0.png"
    assert card["notebook"] == f"hypotheses/{h1.id}/{h1.id}.ipynb"
    assert on_disk["background"].startswith("BG") and on_disk["sources_searched"] == ["wilk2020"]
    assert any(x["path"] == f"hypotheses/{h1.id}/analysis.json" for x in on_disk["files"]) is False
    assert not list(tmp_path.glob("*.tmp"))


def test_write_state_before_preprocessing(tmp_path):
    state = results.write_state(tmp_path, "p1", "preprocess", None, None, "", [], [], None)
    assert state["dataset"] is None and state["brief"] is None and state["files"] == []
