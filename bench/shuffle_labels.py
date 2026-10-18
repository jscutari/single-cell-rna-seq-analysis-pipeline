"""Negative control: permute condition labels across donors, so no real difference remains.

Runs inside the sandbox image (needs scanpy):
    python bench/shuffle_labels.py <processed_dir> <out_dir>

Each new group mixes about half of each true group, keeping the group sizes and
label names, so agents see an ordinary-looking dataset. Columns that would give
the true grouping away (any donor-level value that separates the true groups,
e.g. ventilation status or days since symptoms) are dropped. Every finding an
agent approves on this data is a false positive.
"""

import json
import sys
from pathlib import Path

import numpy as np
import scanpy as sc

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sandbox"))
import preprocess as pp  # noqa: E402

CONDITION, DONOR, CONTROL = "disease", "donor_id", "normal"


def balanced_relabel(true_by_donor: dict[str, str], seed: int = 7) -> dict[str, str]:
    rng = np.random.default_rng(seed)
    case_label = next(c for c in true_by_donor.values() if c != CONTROL)
    cases = sorted(d for d, c in true_by_donor.items() if c != CONTROL)
    controls = sorted(d for d, c in true_by_donor.items() if c == CONTROL)
    rng.shuffle(cases)
    rng.shuffle(controls)
    from_cases = (len(cases) + 1) // 2  # new case group: half the true cases ...
    new_cases = cases[:from_cases] + controls[: len(cases) - from_cases]  # ... topped up with true controls
    return {d: (case_label if d in new_cases else CONTROL) for d in true_by_donor}


def leaky_columns(adata, true_by_donor: dict[str, str]) -> list[str]:
    """Columns whose donor-level values do not overlap between the true groups."""
    leaky = []
    for col in adata.obs.columns:
        if col in (CONDITION, DONOR):
            continue
        per_donor = adata.obs.groupby(DONOR, observed=True)[col].agg(lambda s: s.astype(str).mode().iat[0])
        case_vals = {v for d, v in per_donor.items() if true_by_donor.get(d) != CONTROL}
        ctrl_vals = {v for d, v in per_donor.items() if true_by_donor.get(d) == CONTROL}
        if case_vals and ctrl_vals and not case_vals & ctrl_vals and per_donor.nunique() < len(per_donor):
            leaky.append(col)
    return leaky


def main(src: str, out: str) -> None:
    src_dir, out_dir = Path(src), Path(out)
    adata = sc.read_h5ad(src_dir / "processed.h5ad")
    true_by_donor = adata.obs.groupby(DONOR, observed=True)[CONDITION].first().astype(str).to_dict()
    new_by_donor = balanced_relabel(true_by_donor)
    drop = leaky_columns(adata, true_by_donor)
    adata.obs = adata.obs.drop(columns=drop)
    adata.obs[CONDITION] = adata.obs[DONOR].astype(str).map(new_by_donor).astype("category")
    out_dir.mkdir(parents=True, exist_ok=True)
    adata.write_h5ad(out_dir / "processed.h5ad", compression="gzip")
    gene_format = json.loads((src_dir / "dataset_summary.json").read_text())["gene_id_format"]
    summary = pp.summarize(adata, gene_format)
    summary["removed_columns"] = summary.get("removed_columns", []) + drop
    (out_dir / "dataset_summary.json").write_text(json.dumps(summary, indent=2))
    (out_dir / "umap_points.json").write_text(json.dumps(pp.umap_points(adata)))
    overlap = {g: sum(1 for d, n in new_by_donor.items() if n == g and true_by_donor[d] != CONTROL) for g in set(new_by_donor.values())}
    (out_dir / "shuffle.json").write_text(json.dumps({"true": true_by_donor, "shuffled": new_by_donor, "dropped_columns": drop,
                                                      "true_cases_per_new_group": overlap}, indent=2))
    print(f"shuffled {len(new_by_donor)} donors; true cases per new group: {overlap}; dropped: {drop}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
