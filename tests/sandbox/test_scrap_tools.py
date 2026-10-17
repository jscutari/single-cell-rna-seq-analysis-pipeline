"""sandbox/scrap_tools.py on synthetic data with known answers. Runs inside the
scrap-sandbox image (tests/sandbox/run.sh); skipped where scanpy is missing."""

import sys
from pathlib import Path

import pytest

pytest.importorskip("scanpy")
pytest.importorskip("pydeseq2")

import anndata as ad  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import scipy.sparse as sp  # noqa: E402
from scipy import stats  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "sandbox"))
import scrap_tools as st  # noqa: E402

DONORS = {"C1": "COVID-19", "C2": "COVID-19", "C3": "COVID-19", "H1": "normal", "H2": "normal", "H3": "normal"}


@pytest.fixture
def adata():
    """6 donors x 2 cell types x 30 cells, 200 genes. GENE0 is 8x higher in COVID monocytes."""
    rng = np.random.default_rng(0)
    obs, rows = [], []
    for donor, cond in DONORS.items():
        for ct in ("Mono", "NK"):
            n = 30 if not (donor == "H3" and ct == "NK") else 4  # H3 has too few NK cells
            for _ in range(n):
                mu = np.full(200, 5.0)
                if ct == "Mono" and cond == "COVID-19":
                    mu[0] = 40.0
                rows.append(rng.poisson(mu))
                obs.append({"donor_id": donor, "disease": cond, "cell.type": ct})
    counts = np.array(rows, dtype=np.float32)
    a = ad.AnnData(X=sp.csr_matrix(np.log1p(counts)), obs=pd.DataFrame(obs).astype("category"))
    a.var_names = [f"GENE{i}" for i in range(200)]
    a.obs_names = [f"cell{i}" for i in range(a.n_obs)]
    a.layers["counts"] = sp.csr_matrix(counts)
    return a


def test_pseudobulk_sums_raw_counts_per_donor(adata):
    counts, meta = st.pseudobulk(adata, "donor_id", "disease", "cell.type", "Mono")
    manual = adata[adata.obs["cell.type"] == "Mono"]
    c1 = manual[manual.obs["donor_id"] == "C1"].layers["counts"].sum(axis=0).A1
    assert np.array_equal(counts.loc["C1"].values, c1.astype(int))
    assert counts.dtypes.unique()[0] == np.int64
    assert meta.loc["C1", "condition"] == "COVID-19" and meta.loc["H1", "n_cells"] == 30
    assert list(counts.index) == list(meta.index)


def test_pseudobulk_drops_donors_with_too_few_cells(adata, capsys):
    counts, meta = st.pseudobulk(adata, "donor_id", "disease", "cell.type", "NK", min_cells=10)
    assert "H3" not in meta.index and len(meta) == 5
    assert "dropped ['H3']" in capsys.readouterr().out


def test_pseudobulk_whole_dataset_and_cell_type_lists(adata):
    _, everything = st.pseudobulk(adata, "donor_id", "disease")
    _, both = st.pseudobulk(adata, "donor_id", "disease", "cell.type", ["Mono", "NK"])
    assert everything["n_cells"].sum() == both["n_cells"].sum() == adata.n_obs


def test_deseq_finds_the_planted_gene(adata, capsys):
    counts, meta = st.pseudobulk(adata, "donor_id", "disease", "cell.type", "Mono")
    res = st.deseq(counts, meta, "COVID-19", "normal", n_cpus=1)
    assert res.index[0] == "GENE0"
    assert res.loc["GENE0", "padj"] < 1e-6 and 2.5 < res.loc["GENE0", "log2FoldChange"] < 3.5
    assert res["padj"].is_monotonic_increasing or res["padj"].isna().any()
    assert "COVID-19 (n=3 donors) vs normal (n=3 donors)" in capsys.readouterr().out


def test_deseq_needs_two_donors_per_group(adata):
    counts, meta = st.pseudobulk(adata, "donor_id", "disease", "cell.type", "Mono")
    keep = meta.index[(meta["condition"] == "COVID-19") | (meta.index == "H1")]
    with pytest.raises(ValueError, match="at least 2 donors"):
        st.deseq(counts.loc[keep], meta.loc[keep], "COVID-19", "normal")


def test_donor_scores_average_cells_per_donor(adata, capsys):
    df = st.donor_scores(adata, ["GENE0", "GENE1", "MISSING"], "donor_id", "disease", "cell.type", "Mono")
    mono = adata[(adata.obs["cell.type"] == "Mono") & (adata.obs["donor_id"] == "C2")]
    expected = np.asarray(mono[:, ["GENE0", "GENE1"]].X.mean(axis=1)).ravel().mean()
    assert df.loc["C2", "score"] == pytest.approx(expected, rel=1e-5)
    assert df.loc["C2", "condition"] == "COVID-19" and df.loc["C2", "n_cells"] == 30
    assert "2/3 genes present" in capsys.readouterr().out


def test_compare_groups_matches_scipy():
    df = pd.DataFrame({"condition": ["a"] * 4 + ["b"] * 4, "score": [5, 6, 7, 8, 1, 2, 3, 3.5]})
    out = st.compare_groups(df, "score", "a", "b")
    a, b = np.array([5, 6, 7, 8.0]), np.array([1, 2, 3, 3.5])
    assert out["welch_p"] == pytest.approx(stats.ttest_ind(a, b, equal_var=False).pvalue)
    assert out["mannwhitney_p"] == pytest.approx(stats.mannwhitneyu(a, b).pvalue)
    pooled = np.sqrt((3 * a.var(ddof=1) + 3 * b.var(ddof=1)) / 6)
    assert out["cohens_d"] == pytest.approx((a.mean() - b.mean()) / pooled)
    assert set(out) == {"n_case", "n_control", "mean_case", "mean_control", "mean_diff", "cohens_d",
                        "welch_t", "welch_p", "mannwhitney_u", "mannwhitney_p"}


def test_genesets(tmp_path, monkeypatch):
    (tmp_path / "Lib.gmt").write_text("Interferon Alpha Response\t\tISG15\tIFI6\t\nOther\t\tCD14\n")
    monkeypatch.setattr(st, "GENESETS_DIR", tmp_path)
    assert st.list_genesets("Lib", contains="interferon") == ["Interferon Alpha Response"]
    assert st.load_geneset("Lib", "Interferon Alpha Response") == ["ISG15", "IFI6"]
    with pytest.raises(KeyError, match="list_genesets"):
        st.load_geneset("Lib", "INTERFERON_ALPHA_RESPONSE")


def test_baked_in_gene_sets_exist():
    if not st.GENESETS_DIR.exists():
        pytest.skip("not in the sandbox image")
    assert len(st.load_geneset("MSigDB_Hallmark_2020", "Interferon Alpha Response")) > 50
    assert {p.stem for p in st.GENESETS_DIR.glob("*.gmt")} == {
        "MSigDB_Hallmark_2020", "GO_Biological_Process_2023", "Reactome_2022", "KEGG_2021_Human"}


# --- result tables for the project page ---

def test_helpers_save_numbered_tables_with_sidecars(adata, tmp_path, monkeypatch):
    import json
    monkeypatch.setattr(st, "TABLES_DIR", tmp_path / "tables")
    counts, meta = st.pseudobulk(adata, "donor_id", "disease", "cell.type", "Mono")
    st.deseq(counts, meta, "COVID-19", "normal", n_cpus=1)
    st.donor_scores(adata, ["GENE0"], "donor_id", "disease", "cell.type", "Mono")
    st.donor_scores(adata, ["GENE1"], "donor_id", "disease", "cell.type", "NK")
    names = sorted(p.name for p in (tmp_path / "tables").iterdir())
    assert names == ["de_01.csv", "de_01.json", "scores_01.csv", "scores_01.json", "scores_02.csv", "scores_02.json"]
    de = pd.read_csv(tmp_path / "tables" / "de_01.csv", index_col=0)
    assert list(de.columns) == ["baseMean", "log2FoldChange", "pvalue", "padj"] and de.index[0] == "GENE0"
    assert json.loads((tmp_path / "tables" / "de_01.json").read_text()) == {
        "case": "COVID-19", "control": "normal", "n_case": 3, "n_control": 3}
    assert json.loads((tmp_path / "tables" / "scores_02.json").read_text())["celltype"] == "NK"


def test_unwritable_tables_dir_never_breaks_the_analysis(adata, tmp_path, monkeypatch):
    blocker = tmp_path / "file"
    blocker.write_text("not a directory")
    monkeypatch.setattr(st, "TABLES_DIR", blocker / "tables")
    df = st.donor_scores(adata, ["GENE0"], "donor_id", "disease", "cell.type", "Mono")
    assert len(df) == 6
