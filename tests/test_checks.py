"""agents/checks.py: the deterministic rules the critic cannot argue with."""

import contextlib
import io
from types import SimpleNamespace

import pandas as pd
import pytest

from agents import checks
from agents.checks import format_report, parse_design, run_checks
from shared.schemas import Brief, CellStatus, CodeCell, Finding

DESIGN_OK = {"donors_per_condition": {"COVID-19": 7, "normal": 6}, "confounded": []}


def cell(source: str, status=CellStatus.ok, stdout="") -> CodeCell:
    return CodeCell(hypothesis_id="h", index=0, source=source, status=status, stdout=stdout)


def finding(p_adj=0.01, effect=1.5) -> Finding:
    return Finding(hypothesis_id="h", claim="c", test="t", p_adj=p_adj, effect_size=effect)


def by_name(results) -> dict:
    return {c.name: c for c in results}


PSEUDOBULK = "counts, meta = pseudobulk(adata, 'donor_id', 'disease')\nres = deseq(counts, meta, 'a', 'b')"


def test_all_pass_for_a_good_donor_level_analysis():
    r = by_name(run_checks([cell(PSEUDOBULK)], finding(), DESIGN_OK))
    assert {k: v.status for k, v in r.items()} == {
        "pseudobulk": "pass", "multiple_testing": "pass", "significance": "pass",
        "effect_size": "pass", "replicates": "pass", "confounding": "pass"}


def test_donor_scores_counts_as_donor_level():
    assert by_name(run_checks([cell("df = donor_scores(adata, g, 'd', 'c')")], finding(), DESIGN_OK))[
        "pseudobulk"].status == "pass"


@pytest.mark.parametrize("code", ["sc.tl.rank_genes_groups(adata, 'disease')",
                                  "stats.mannwhitneyu(a.X, b.X)", "ttest_ind(x, y)"])
def test_cell_level_tests_fail(code):
    assert by_name(run_checks([cell(code)], finding(), DESIGN_OK))["pseudobulk"].status == "fail"


def test_no_aggregation_found_warns():
    assert by_name(run_checks([cell("print(1)")], finding(), DESIGN_OK))["pseudobulk"].status == "warn"


def test_failed_cells_are_ignored():
    r = by_name(run_checks([cell(PSEUDOBULK, status=CellStatus.error)], finding(), DESIGN_OK))
    assert r["pseudobulk"].status == "warn"


def test_multiple_testing_warns_when_padj_claimed_without_correction_in_code():
    assert by_name(run_checks([cell("x = donor_scores(...)")], finding(), DESIGN_OK))[
        "multiple_testing"].status == "warn"


def test_missing_padj_fails_multiple_testing_and_significance():
    r = by_name(run_checks([cell(PSEUDOBULK)], finding(p_adj=None), DESIGN_OK))
    assert r["multiple_testing"].status == "fail" and r["significance"].status == "fail"


@pytest.mark.parametrize("p, status", [(0.049, "pass"), (0.05, "fail"), (0.078, "fail")])
def test_significance_threshold(p, status):
    assert by_name(run_checks([cell(PSEUDOBULK)], finding(p_adj=p), DESIGN_OK))["significance"].status == status


def test_missing_effect_size_fails():
    assert by_name(run_checks([cell(PSEUDOBULK)], finding(effect=None), DESIGN_OK))["effect_size"].status == "fail"


def test_too_few_donors_fails():
    design = {"donors_per_condition": {"COVID-19": 7, "normal": 2}, "confounded": []}
    r = by_name(run_checks([cell(PSEUDOBULK)], finding(), design))["replicates"]
    assert r.status == "fail" and "normal" in r.detail


def test_unknown_design_warns():
    assert by_name(run_checks([cell(PSEUDOBULK)], finding(), {}))["replicates"].status == "warn"


def test_confounders_warn():
    design = {**DESIGN_OK, "confounded": ["Admission: COVID-19=ICU, normal=N/A"]}
    r = by_name(run_checks([cell(PSEUDOBULK)], finding(), design))["confounding"]
    assert r.status == "warn" and "Admission" in r.detail


def test_blocking_checks_are_significance_and_replicates():
    assert checks.BLOCKING == {"significance", "replicates"}


def test_format_report_has_one_line_per_check():
    report = format_report(run_checks([cell(PSEUDOBULK)], finding(p_adj=0.2), DESIGN_OK))
    lines = report.splitlines()
    assert len(lines) == 6 and "[FAIL] significance" in report and "[PASS] effect_size" in report


def run_design_cell(obs: pd.DataFrame, brief: Brief) -> dict:
    """Execute the kernel cell the way the kernel would, against a fake dataset."""
    code = checks.design_check_code(brief)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        exec(code, {"_ADATA": SimpleNamespace(obs=obs), "adata": None})
    return parse_design(cell("", stdout=out.getvalue()))


def test_design_cell_counts_donors_and_finds_confounders(brief):
    rows = []
    for donor, cond, admission, sex in [("C1", "COVID-19", "ICU", "male"), ("C2", "COVID-19", "ICU", "female"),
                                        ("H1", "normal", "N/A", "male"), ("H2", "normal", "N/A", "female")]:
        rows += [{"donor_id": donor, "disease": cond, "Admission": admission, "sex": sex,
                  "cell.type.coarse": "NK", "disease_ontology_term_id": cond}] * 5
    obs = pd.DataFrame(rows).astype("category")
    design = run_design_cell(obs, brief)
    assert design["donors_per_condition"] == {"COVID-19": 2, "normal": 2}
    assert len(design["confounded"]) == 1 and design["confounded"][0].startswith("Admission")


def test_design_cell_uses_the_untouched_dataset_even_if_adata_was_reassigned(brief):
    obs = pd.DataFrame({"donor_id": ["C1", "H1"], "disease": ["COVID-19", "normal"],
                        "cell.type.coarse": ["NK", "NK"]})
    code = checks.design_check_code(brief)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        exec(code, {"_ADATA": SimpleNamespace(obs=obs), "adata": "reassigned by an agent"})
    assert parse_design(cell("", stdout=out.getvalue()))["donors_per_condition"] == {"COVID-19": 1, "normal": 1}


def test_parse_design_without_marker_returns_empty():
    assert parse_design(cell("", stdout="Traceback ...")) == {}
