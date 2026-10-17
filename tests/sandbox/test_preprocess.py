"""sandbox/preprocess.py on a synthetic CELLxGENE-style file. Runs inside the sandbox image."""

import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("scanpy")

import anndata as ad  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import scipy.sparse as sp  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "sandbox"))
import preprocess as pp  # noqa: E402

N_CELLS, N_GENES = 300, 2500


def cellxgene_like(path: Path, integer_raw=True) -> Path:
    """Normalized X, integer counts in .raw, Ensembl IDs with symbols in feature_name, leaky score columns."""
    rng = np.random.default_rng(1)
    counts = rng.negative_binomial(2, 0.3, size=(N_CELLS, N_GENES)).astype(np.float32)
    counts[:5, :] = 0
    counts[:5, :50] = 1  # 5 low-quality cells with 50 genes each
    obs = pd.DataFrame({
        "donor_id": rng.choice(["C1", "C2", "H1", "H2"], N_CELLS),
        "disease": rng.choice(["COVID-19", "normal"], N_CELLS),
        "cell.type.coarse": rng.choice(["CD14 Monocyte", "NK", "B"], N_CELLS),
        "IFN1": rng.normal(size=N_CELLS), "HLA1": rng.normal(size=N_CELLS),
        "nCount_RNA": counts.sum(1),
    }, index=[f"c{i}" for i in range(N_CELLS)]).astype({"donor_id": "category", "disease": "category"})
    symbols = [f"GENE{i}" for i in range(N_GENES)]
    symbols[0], symbols[1], symbols[2] = "MT-CO1", "ISG15", "ISG15"  # duplicate symbol on purpose
    var = pd.DataFrame({"feature_name": symbols}, index=[f"ENSG{i:011d}" for i in range(N_GENES)])
    raw = ad.AnnData(X=sp.csr_matrix(counts if integer_raw else counts + 0.5), obs=obs, var=var)
    a = raw.copy()
    a.X = sp.csr_matrix(np.log1p(counts))
    a.raw = raw
    a.write_h5ad(path)
    return path


def test_full_pipeline(tmp_path):
    src = cellxgene_like(tmp_path / "in.h5ad")
    pp.main(str(src), str(tmp_path / "out"))
    out = tmp_path / "out"
    a = ad.read_h5ad(out / "processed.h5ad")

    assert a.n_obs == N_CELLS - 5                      # min_genes=100 drops the 5 bad cells
    assert "ISG15" in a.var_names and "ISG15-1" in a.var_names and "MT-CO1" in a.var_names
    assert a.var.loc["ISG15", "ensembl_id"].startswith("ENSG")
    assert "IFN1" not in a.obs and "HLA1" not in a.obs
    counts = a.layers["counts"]
    assert np.allclose(counts.data, np.round(counts.data))  # raw integer counts kept
    total = np.asarray(np.expm1(a.X).sum(axis=1)).ravel()
    assert np.allclose(total, 1e4, rtol=1e-3)               # normalize_total(1e4) + log1p
    assert {"X_pca", "X_umap"} <= set(a.obsm) and a.var["highly_variable"].sum() == 2000
    assert (out / "umap_overview.png").stat().st_size > 1000

    summary = json.loads((out / "dataset_summary.json").read_text())
    assert summary["n_cells"] == N_CELLS - 5 and summary["removed_columns"] == ["IFN1", "HLA1"]
    assert summary["gene_id_format"].startswith("ensembl (re-indexed to symbols")
    assert summary["obs_columns"]["disease"]["counts"].keys() == {"COVID-19", "normal"}
    assert "range" in summary["obs_columns"]["nCount_RNA"]
    assert "IFN1" not in summary["obs_columns"]


def test_rejects_data_without_integer_counts(tmp_path):
    src = cellxgene_like(tmp_path / "in.h5ad", integer_raw=False)
    with pytest.raises(SystemExit, match="integer counts"):
        pp.load_counts(src)


def test_symbol_indexed_data_is_left_alone():
    a = ad.AnnData(X=sp.csr_matrix(np.ones((2, 2))), var=pd.DataFrame(index=["ISG15", "CD14"]))
    assert pp.use_gene_symbols(a) == "symbol" and list(a.var_names) == ["ISG15", "CD14"]


def test_umap_points_for_charts(tmp_path):
    src = cellxgene_like(tmp_path / "in.h5ad")
    pp.main(str(src), str(tmp_path / "out"))
    pts = json.loads((tmp_path / "out" / "umap_points.json").read_text())
    assert len(pts["x"]) == len(pts["y"]) == N_CELLS - 5  # fewer cells than UMAP_POINTS: keep all
    assert 0 <= min(pts["x"]) and max(pts["x"]) <= 1
    assert set(pts["labels"]) >= {"donor_id", "disease", "cell.type.coarse"}
    assert "nCount_RNA" not in pts["labels"] and len(pts["labels"]["disease"]) == len(pts["x"])
