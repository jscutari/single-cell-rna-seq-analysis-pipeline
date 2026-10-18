"""bench/suite.py: scoring against the papers' findings, briefs, and the summary report."""

import json

from bench import suite
from shared.schemas import Finding


def f(claim, p=0.01, verdict="approve"):
    return Finding(hypothesis_id="h", claim=claim, test="t", p_adj=p, critic_verdict=verdict)


def test_every_dataset_has_findings_from_its_abstract():
    for key, ds in suite.REGISTRY.items():
        assert ds["findings"], key
        for item in ds["findings"]:
            assert item["name"] and item["topic"]


def test_recovery_needs_topic_direction_significance_and_acceptance():
    rubric = suite.REGISTRY["wilk"]["findings"]
    findings = [f("HLA-DR expression is lower in CD14 monocytes"), f("Interferon response is higher", p=0.2),
                f("Neutrophils expand in COVID-19", verdict="reject")]
    assert suite.recovered(findings, rubric) == ["HLA class II down"]


def test_topic_only_rules_ignore_direction():
    rubric = suite.REGISTRY["jakel"]["findings"]
    assert suite.recovered([f("Oligodendrocyte subcluster proportions differ in MS")], rubric) == [
        "altered oligodendrocyte subpopulations"]


def test_brief_is_neutral_and_uses_standard_columns():
    summary = {"obs_columns": {"disease": {"counts": {"normal": 5, "Alzheimer disease": 5}}}}
    b = suite.brief_for("leng", summary)
    assert b.condition_labels == ["Alzheimer disease", "normal"]
    assert (b.condition_column, b.donor_column, b.celltype_column) == ("disease", "donor_id", "cell_type")
    assert "RORB" not in b.goals and "astrocyte" not in b.goals.lower() and b.online_search is False


def test_shuffled_control_maps_to_its_source_and_has_no_rubric():
    assert suite.dataset_info("wilk_shuffled")["name"] == suite.REGISTRY["wilk"]["name"]


def test_report_tables(tmp_path):
    rows = [
        {"dataset": "wilk", "variant": "multi", "repeat": 1, "error": None, "recovered": ["HLA class II down"],
         "n_findings": 5, "accepted_significant": 2, "rejected_by_critic": 3, "wall_s": 150, "llm_calls": 60,
         "cells": 30, "cells_ok": 24, "gen_tokens_per_s": 900, "peak_concurrent_requests": 5, "llm_latency_p50_ms": 2000},
        {"dataset": "wilk_shuffled", "variant": "multi", "repeat": 1, "error": None, "recovered": [],
         "n_findings": 5, "accepted_significant": 0, "rejected_by_critic": 5},
        {"dataset": "wilk_shuffled", "variant": "no_critic", "repeat": 1, "error": None, "recovered": [],
         "n_findings": 5, "accepted_significant": 3, "rejected_by_critic": 0},
        {"dataset": "leng", "variant": "multi", "repeat": 1, "error": "TimeoutError: x"},
    ]
    text = suite.report(rows)
    assert "| COVID-19 PBMC (Wilk et al. 2020) | 3 | 1.0 / 3 (n=1)" in text
    assert "| multi | 1 | 5 | **0** | 5 |" in text and "| no_critic | 1 | 5 | **3** | 0 |" in text
    assert "| Cells that ran (%) | 80 |" in text
    assert "1 run(s) failed: leng/multi/r1" in text
    out = tmp_path / "s.jsonl"
    out.write_text("\n".join(json.dumps(r) for r in rows))
    assert len(suite.load(out)) == 4
