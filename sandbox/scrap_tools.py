"""Tested statistics helpers, imported in every kernel as `from scrap_tools import *`.

Small models get library APIs wrong more often than they get the science wrong,
so the error-prone parts (pseudobulk, DESeq2, donor-level tests) live here.
Every helper prints the numbers it computed, so agents can reason from text.
"""

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import scipy.sparse as sp
from scipy import stats
from statsmodels.stats.multitest import multipletests

GENESETS_DIR = Path(os.environ.get("GENESETS_DIR", "/opt/genesets"))
# Result tables are saved here (the hypothesis folder is mounted at /work), so the
# app can chart the exact numbers the statistics were computed on.
TABLES_DIR = Path(os.environ.get("SCRAP_TABLES_DIR", "/work/tables"))


def _save_table(kind: str, df: pd.DataFrame, meta: dict) -> None:
    """Write tables/<kind>_NN.csv plus a .json sidecar. Never fails the analysis."""
    try:
        TABLES_DIR.mkdir(parents=True, exist_ok=True)
        n = len(list(TABLES_DIR.glob(f"{kind}_*.csv"))) + 1
        df.to_csv(TABLES_DIR / f"{kind}_{n:02d}.csv")
        (TABLES_DIR / f"{kind}_{n:02d}.json").write_text(json.dumps(meta, default=str))
    except OSError:
        pass

__all__ = ["pseudobulk", "deseq", "donor_scores", "compare_groups", "load_geneset",
           "list_genesets", "multipletests"]


def _subset(adata, celltype_col, celltype):
    if celltype is None:
        return adata
    cts = [celltype] if isinstance(celltype, str) else list(celltype)
    return adata[adata.obs[celltype_col].isin(cts)]


def pseudobulk(adata, donor_col, condition_col, celltype_col=None, celltype=None, min_cells=10):
    """Sum raw counts per donor (optionally within one cell type).

    Returns (counts, meta): counts is donors x genes (int), meta has the
    condition and n_cells per donor. Donors with < min_cells cells are dropped.
    """
    sub = _subset(adata, celltype_col, celltype)
    x = sub.layers["counts"] if "counts" in sub.layers else sub.X
    donors = sub.obs[donor_col].astype(str).values
    levels = np.unique(donors)
    onehot = sp.csr_matrix((np.ones(len(donors)), (np.searchsorted(levels, donors), np.arange(len(donors)))),
                           shape=(len(levels), len(donors)))
    summed = onehot @ (x if sp.issparse(x) else sp.csr_matrix(x))
    counts = pd.DataFrame(np.asarray(summed.todense()).round().astype(np.int64),
                          index=levels, columns=sub.var_names)
    meta = (sub.obs.assign(_d=donors).groupby("_d", observed=True)
            .agg(condition=(condition_col, "first"), n_cells=(condition_col, "size")))
    meta.index.name = None
    meta["condition"] = meta["condition"].astype(str)
    keep = meta.index[meta["n_cells"] >= min_cells]
    dropped = sorted(set(meta.index) - set(keep))
    meta, counts = meta.loc[keep], counts.loc[keep]
    label = f" in {celltype}" if celltype is not None else ""
    print(f"Pseudobulk{label}: {len(keep)} donors (dropped {dropped or 'none'} with <{min_cells} cells)")
    print(meta.groupby("condition")["n_cells"].agg(["count", "median", "min"])
          .rename(columns={"count": "n_donors", "median": "median_cells", "min": "min_cells"}).to_string())
    return counts, meta


def deseq(counts, meta, case, control, min_total_count=10, n_cpus=4):
    """DESeq2 (pydeseq2) on pseudobulk counts: case vs control. Returns results sorted by padj.

    Columns: baseMean, log2FoldChange (case/control), lfcSE, stat, pvalue, padj (Benjamini-Hochberg).
    """
    from pydeseq2.dds import DeseqDataSet
    from pydeseq2.ds import DeseqStats

    meta = meta[meta["condition"].isin([case, control])]
    counts = counts.loc[meta.index]
    counts = counts.loc[:, counts.sum(axis=0) >= min_total_count]
    n = meta["condition"].value_counts()
    print(f"DESeq2: {case} (n={n.get(case, 0)} donors) vs {control} (n={n.get(control, 0)} donors), "
          f"{counts.shape[1]} genes tested")
    if min(n.get(case, 0), n.get(control, 0)) < 2:
        raise ValueError("Need at least 2 donors per group for DESeq2.")
    dds = DeseqDataSet(counts=counts, metadata=meta[["condition"]], design="~condition",
                       quiet=True, n_cpus=n_cpus)
    dds.deseq2()
    ds = DeseqStats(dds, contrast=["condition", case, control], quiet=True, n_cpus=n_cpus)
    ds.summary()
    res = ds.results_df.sort_values("padj")
    sig = res[res["padj"] < 0.05]
    _save_table("de", res[["baseMean", "log2FoldChange", "pvalue", "padj"]],
                {"case": case, "control": control, "n_case": int(n.get(case, 0)), "n_control": int(n.get(control, 0))})
    print(f"{len(sig)} genes with padj < 0.05 ({(sig['log2FoldChange'] > 0).sum()} up, "
          f"{(sig['log2FoldChange'] < 0).sum()} down in {case})")
    return res


def donor_scores(adata, genes, donor_col, condition_col, celltype_col=None, celltype=None, min_cells=10):
    """Mean log-normalized expression of a gene set per cell, averaged per donor.

    Returns a DataFrame indexed by donor with columns condition, n_cells, score.
    """
    sub = _subset(adata, celltype_col, celltype)
    present = [g for g in genes if g in sub.var_names]
    missing = sorted(set(genes) - set(present))
    print(f"Gene set: {len(present)}/{len(genes)} genes present" + (f" (missing: {missing[:10]})" if missing else ""))
    x = sub[:, present].X
    cell_score = np.asarray(x.mean(axis=1)).ravel()
    df = (pd.DataFrame({"donor": sub.obs[donor_col].astype(str).values,
                        "condition": sub.obs[condition_col].astype(str).values, "score": cell_score})
          .groupby("donor").agg(condition=("condition", "first"), n_cells=("score", "size"), score=("score", "mean")))
    df = df[df["n_cells"] >= min_cells]
    print(df.sort_values(["condition", "score"]).to_string(float_format=lambda v: f"{v:.4f}"))
    _save_table("scores", df, {"n_genes": len(present), "celltype": celltype})
    return df


def compare_groups(df, value_col, case, control, group_col="condition"):
    """Donor-level comparison: Welch t-test, Mann-Whitney U, mean difference and Cohen's d."""
    a = df.loc[df[group_col] == case, value_col].astype(float)
    b = df.loc[df[group_col] == control, value_col].astype(float)
    t = stats.ttest_ind(a, b, equal_var=False)
    u = stats.mannwhitneyu(a, b, alternative="two-sided")
    pooled = np.sqrt(((len(a) - 1) * a.var(ddof=1) + (len(b) - 1) * b.var(ddof=1)) / (len(a) + len(b) - 2))
    out = {"n_case": len(a), "n_control": len(b), "mean_case": a.mean(), "mean_control": b.mean(),
           "mean_diff": a.mean() - b.mean(), "cohens_d": (a.mean() - b.mean()) / pooled if pooled > 0 else np.nan,
           "welch_t": t.statistic, "welch_p": t.pvalue, "mannwhitney_u": u.statistic, "mannwhitney_p": u.pvalue}
    print(", ".join(f"{k}={v:.4g}" if isinstance(v, float) else f"{k}={v}" for k, v in out.items()))
    return out


def list_genesets(library, contains=""):
    """Term names in a GMT library (MSigDB_Hallmark_2020, GO_Biological_Process_2023, Reactome_2022, KEGG_2021_Human)."""
    terms = [line.split("\t", 1)[0] for line in (GENESETS_DIR / f"{library}.gmt").read_text().splitlines()]
    return [t for t in terms if contains.lower() in t.lower()]


def load_geneset(library, term):
    """Genes in one term, e.g. load_geneset('MSigDB_Hallmark_2020', 'Interferon Alpha Response')."""
    for line in (GENESETS_DIR / f"{library}.gmt").read_text().splitlines():
        name, _, *genes = line.split("\t")
        if name == term:
            return [g for g in genes if g]
    raise KeyError(f"{term!r} not in {library}; try list_genesets({library!r}, contains=...)")
