"""Deterministic stats checks the critic gets.

The critic is an LLM and can be talked into things; these checks can't. They
look at the code that ran, the finding being claimed, and (via one kernel
cell) the study design, and produce a short report the critic must address.
"""

import json
import re
from dataclasses import dataclass
from typing import Literal

from shared.schemas import Brief, CodeCell, Finding

Status = Literal["pass", "warn", "fail"]
MIN_DONORS_PER_GROUP = 3
ALPHA = 0.05
# Checks the critic cannot override: a FAIL here means the finding is rejected.
BLOCKING = {"significance", "replicates"}
_MARK = "__SCRAP_DESIGN__"


@dataclass
class Check:
    name: str
    status: Status
    detail: str


def design_check_code(brief: Brief) -> str:
    """Kernel cell that prints donors per condition and covariates confounded with condition, as JSON."""
    return f"""
import json as _json
_cond, _donor = {brief.condition_column!r}, {brief.donor_column!r}
_skip = {{_cond, _donor, {brief.celltype_column!r}}}
_obs = _ADATA.obs  # full dataset, even if a cell reassigned `adata`
_donors = _obs.groupby(_donor, observed=True)[_cond].first().astype(str)
_confounded = []
for _c in _obs.columns:
    if _c in _skip or _c.endswith("_ontology_term_id") or not 2 <= _obs[_c].nunique() <= 10:
        continue
    _per_donor = _obs.groupby(_donor, observed=True)[_c].agg(lambda s: s.astype(str).mode().iat[0])
    _tab = {{k: set(v) for k, v in _per_donor.groupby(_donors)}}
    # Confounded: each condition has one value of this column and the values differ.
    if all(len(v) == 1 for v in _tab.values()) and len(set().union(*_tab.values())) == len(_tab):
        _confounded.append(f"{{_c}}: " + ", ".join(f"{{k}}={{next(iter(v))}}" for k, v in _tab.items()))
print({_MARK!r} + _json.dumps({{"donors_per_condition": _donors.value_counts().to_dict(), "confounded": _confounded}}))
"""


def parse_design(cell: CodeCell) -> dict:
    for line in cell.stdout.splitlines():
        if line.startswith(_MARK):
            return json.loads(line[len(_MARK):])
    return {}


def run_checks(cells: list[CodeCell], finding: Finding, design: dict) -> list[Check]:
    code = "\n".join(c.source for c in cells if c.status == "ok")
    out: list[Check] = []

    # 1. Donors, not cells, are the replicates.
    if re.search(r"\bpseudobulk\(|\bdonor_scores\(", code):
        out.append(Check("pseudobulk", "pass", "Statistics computed at donor level."))
    elif re.search(r"rank_genes_groups|mannwhitneyu|ttest_ind|wilcoxon", code):
        out.append(Check("pseudobulk", "fail",
                         "A test ran on individual cells. Cells from one donor are not independent; "
                         "aggregate per donor (pseudobulk / donor_scores) before testing."))
    else:
        out.append(Check("pseudobulk", "warn", "No donor-level aggregation found in the code."))

    # 2. Multiple-testing correction.
    if finding.p_adj is not None and re.search(r"padj|multipletests|\bdeseq\(|fdr", code, re.I):
        out.append(Check("multiple_testing", "pass", f"Adjusted p = {finding.p_adj:.3g}."))
    elif finding.p_adj is not None:
        out.append(Check("multiple_testing", "warn",
                         "A p_adj is claimed but no correction (padj / multipletests) appears in the code."))
    else:
        out.append(Check("multiple_testing", "fail", "No adjusted p-value reported."))

    # 2b. Significance. A correctly reported null result is still not a finding.
    if finding.p_adj is None or finding.p_adj >= ALPHA:
        out.append(Check("significance", "fail",
                         f"Adjusted p = {finding.p_adj} is not below {ALPHA}; this cannot be approved as a finding."))
    else:
        out.append(Check("significance", "pass", f"Adjusted p = {finding.p_adj:.3g} < {ALPHA}."))

    # 3. Effect size.
    if finding.effect_size is None:
        out.append(Check("effect_size", "fail", "No effect size reported (log2 fold change, Cohen's d, ...)."))
    else:
        out.append(Check("effect_size", "pass", f"Effect size = {finding.effect_size:.3g}."))

    # 4. Enough donors per group.
    donors = design.get("donors_per_condition", {})
    if not donors:
        out.append(Check("replicates", "warn", "Could not count donors per condition."))
    else:
        low = {k: v for k, v in donors.items() if v < MIN_DONORS_PER_GROUP}
        summary = ", ".join(f"{k}: {v}" for k, v in donors.items())
        out.append(Check("replicates", "fail" if low else "pass",
                         f"Donors per condition: {summary}" + (f" (<{MIN_DONORS_PER_GROUP}: {list(low)})" if low else "")))

    # 5. Covariates that move in lockstep with condition can't be separated from it.
    confounded = design.get("confounded", [])
    if confounded:
        out.append(Check("confounding", "warn",
                         "These covariates are perfectly confounded with condition, so their effects cannot "
                         "be separated from it: " + "; ".join(confounded)))
    else:
        out.append(Check("confounding", "pass", "No covariate perfectly confounded with condition."))
    return out


def format_report(checks: list[Check]) -> str:
    icon = {"pass": "PASS", "warn": "WARN", "fail": "FAIL"}
    return "\n".join(f"[{icon[c.status]}] {c.name}: {c.detail}" for c in checks)
