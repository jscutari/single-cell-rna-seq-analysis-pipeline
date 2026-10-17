"""Fixed QC + normalization for the dataset.

Every hypothesis starts from the same processed.h5ad, so agents never redo
(or botch) normalization. Runs inside the sandbox image:

  docker run --rm -v <data_dir>:/data -v <repo>/sandbox:/app:ro scrap-sandbox \
      python /app/preprocess.py /data/raw/input.h5ad /data/<project_id>

Writes <out_dir>/processed.h5ad and <out_dir>/dataset_summary.json.
"""

import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import scanpy as sc
import scipy.sparse as sp

# Precomputed scores that give away findings we benchmark on (Wilk et al.'s
# interferon and HLA module scores). Agents must derive these themselves.
LEAKY_COLUMNS = ["IFN1", "HLA1"]
# How many distinct values a column may have and still be listed in full.
MAX_LEVELS = 40


def load_counts(path: Path) -> sc.AnnData:
    adata = sc.read_h5ad(path)
    # CELLxGENE stores normalized values in X and integer counts in raw.
    if adata.raw is not None:
        counts = adata.raw.to_adata()
        counts.obs = adata.obs
        for key in adata.obsm:
            counts.obsm[key] = adata.obsm[key]
        adata = counts
    x = adata.X[:500]
    x = x.toarray() if sp.issparse(x) else np.asarray(x)
    if not np.allclose(x, np.round(x)):
        sys.exit("No integer counts found in X or raw; pseudobulk DE needs raw counts.")
    adata.X = sp.csr_matrix(adata.X, dtype=np.float32)
    return adata


def use_gene_symbols(adata: sc.AnnData) -> str:
    """Index genes by symbol (agents write ISG15, not ENSG00000187608). Returns the original ID format."""
    if "feature_name" in adata.var and adata.var_names[0].startswith("ENS"):
        adata.var["ensembl_id"] = adata.var_names
        adata.var_names = adata.var["feature_name"].astype(str)
        adata.var_names_make_unique()
        adata.var.index.name = None  # else it clashes with the feature_name column on write
        return "ensembl (re-indexed to symbols; original IDs in var['ensembl_id'])"
    return "symbol"


def preprocess(adata: sc.AnnData) -> sc.AnnData:
    adata.obs = adata.obs.drop(columns=[c for c in LEAKY_COLUMNS if c in adata.obs])
    adata.var["mt"] = adata.var_names.str.startswith("MT-")
    sc.pp.calculate_qc_metrics(adata, qc_vars=["mt"], inplace=True, percent_top=None, log1p=False)
    sc.pp.filter_cells(adata, min_genes=100)
    sc.pp.filter_genes(adata, min_cells=3)

    adata.layers["counts"] = adata.X.copy()
    sc.pp.normalize_total(adata, target_sum=1e4)
    sc.pp.log1p(adata)

    sc.pp.highly_variable_genes(adata, n_top_genes=2000, flavor="seurat_v3", layer="counts")
    sc.pp.pca(adata, n_comps=50, mask_var="highly_variable")
    sc.pp.neighbors(adata, n_neighbors=15)
    sc.tl.umap(adata)
    return adata


def summarize(adata: sc.AnnData, gene_id_format: str) -> dict:
    """What the intake agent sees: enough to guess condition/donor/cell-type columns."""
    columns = {}
    for col in adata.obs.columns:
        s = adata.obs[col]
        info = {"dtype": str(s.dtype), "n_unique": int(s.nunique())}
        if info["n_unique"] <= MAX_LEVELS:
            info["counts"] = {str(k): int(v) for k, v in s.value_counts().items()}
        elif pd.api.types.is_numeric_dtype(s):
            info["range"] = [float(s.min()), float(s.max())]
        columns[col] = info
    return {
        "n_cells": adata.n_obs,
        "n_genes": adata.n_vars,
        "gene_id_format": gene_id_format,
        "example_genes": list(adata.var_names[:10]),
        "layers": {"X": "log1p(normalize_total 1e4)", "counts": "raw integer counts"},
        "embeddings": list(adata.obsm.keys()),
        "obs_columns": columns,
        "removed_columns": LEAKY_COLUMNS,
    }


def main(in_path: str, out_dir: str) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    adata = load_counts(Path(in_path))
    gene_id_format = use_gene_symbols(adata)
    adata = preprocess(adata)
    adata.write_h5ad(out / "processed.h5ad", compression="gzip")
    (out / "dataset_summary.json").write_text(json.dumps(summarize(adata, gene_id_format), indent=2))

    sc.pl.umap(adata, color=[c for c in ["cell.type.coarse", "disease", "donor_id"] if c in adata.obs],
               ncols=3, show=False, save=False)
    plt.savefig(out / "umap_overview.png", dpi=120, bbox_inches="tight")
    print(f"{adata.n_obs} cells x {adata.n_vars} genes -> {out}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
