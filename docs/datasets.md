# More datasets: plan

**Status:** plan only. Nothing here is downloaded or wired in yet.

## What a usable dataset needs
- An annotated `.h5ad` with raw counts.
- A **case vs control** design with **several donors per group**. Our statistics use donors as the replicates.
- A size a sandbox kernel can load: kernels are capped at 24 GB of memory.
- Ideally, **a paper with known findings**, so recovery can be scored as with COVID.

All candidates come from **CZ CELLxGENE**. Its schema guarantees standard `donor_id`, `disease` and `cell_type` columns, so the intake step and preprocessing work unchanged. The catalog has 139 datasets with exactly "normal" plus one disease and at least 8 donors (queried 2026-10-17).

## Shortlist

| # | Dataset | Cells | Donors | Size | Why |
| --- | --- | --- | --- | --- | --- |
| 1 | **Schulte-Schrepping et al. 2020, Cell**: COVID-19 PBMC | 90,957 | 39 | 718 MB | Same disease as Wilk, different cohort. **Do results replicate?** Many donors, so the donor-level statistics are strong. |
| 2 | **Melms et al. 2021, Nature**: lethal COVID-19 lung (single nuclei) | 116,313 | 27 | 502 MB | Same disease, **different tissue and assay** (lung, snRNA-seq). Tests whether prompts generalize beyond blood. |
| 3 | **Leng et al. 2021, Nat Neurosci**: Alzheimer's disease, entorhinal cortex (single nuclei) | 42,528 | 10 | 125 MB | **Different organ and disease.** The known findings are about cell-type composition, not gene programs. |
| 4 | **Jäkel et al. 2019, Nature**: multiple sclerosis, oligodendrocytes (single nuclei) | 17,799 | 9 | 45 MB | Tiny and fast: a **2-minute smoke test** for prompt changes. Few donors, so it also checks that the replicate rule blocks weak claims. |
| (5) | Lee et al. 2020: COVID-19 PBMC | 43,512 | 12 | 433 MB | Optional third COVID cohort. |
| (6) | Mouse post-flu lung time series | 123,154 | 25 | 1.6 GB | **Stress test only:** mouse gene symbols don't match our human gene sets. Skip unless we add mouse gene sets. |

Download URLs (CELLxGENE, stable):
- Schulte-Schrepping: `https://datasets.cellxgene.cziscience.com/0cb10876-cd52-4795-bae7-7adee5d6a4c5.h5ad`
- Melms: `https://datasets.cellxgene.cziscience.com/1792df55-7cfe-4564-afcf-4bb3ffb73bc0.h5ad`
- Leng (entorhinal cortex, all cell types): `https://datasets.cellxgene.cziscience.com/bd45e577-ee39-4e44-942f-c26be669227d.h5ad`
- Jäkel: `https://datasets.cellxgene.cziscience.com/8bbea7c5-c742-4c27-a597-0f1e1383bb48.h5ad`
- Lee: `https://datasets.cellxgene.cziscience.com/a26c0d2d-65e7-4b9b-a314-a75c807a7c1e.h5ad`

## Findings to recover (from memory; check each against the paper before scoring)
- **Schulte-Schrepping:** HLA-DR-low monocytes and immature, dysfunctional neutrophils in severe COVID-19.
- **Melms:** monocyte-derived macrophages accumulate; pathological (CTHRC1+) fibroblasts expand; alveolar type 2 cells are impaired.
- **Leng:** RORB+ excitatory neurons are selectively lost as disease progresses; reactive astrocytes.
- **Jäkel:** oligodendrocyte subpopulations shift in MS white matter.

Add each paper's PDF as a project source, so the literature agent can label these findings `known`.

## Work needed to use them
1. **Download and preprocess:** extend `infra/setup_brev.sh`'s download list. Each dataset becomes a project folder with `dataset.h5ad`, and the orchestrator's cache preprocesses it once.
2. **Make the benchmark dataset-agnostic:** `bench/covid_recovery.py` hard-codes the Wilk findings and the brief. Move both into a per-dataset file (`bench/datasets/<name>.json`: URL, brief goals, findings to recover with keyword rules), and loop over datasets.
3. **Watch for:**
   - Datasets of 90–116k cells take longer to load in each kernel's preamble (estimate: 20–40 s). Fine, but it adds to the wall-clock time.
   - Single-nucleus data has few mitochondrial reads, so mito-based QC tells us little. Our fixed preprocessing doesn't filter on it, so this needs no change.
   - With 9–10 donors, per-cell-type groups can fall below 3 donors. The replicate check blocks those claims, which is correct, but expect more rejections.

## Prompt review: what to measure on each run
Every model call is already logged as an `llm_call` event, so a review can be computed from a run's events:

| Agent | Signal | Read from |
| --- | --- | --- |
| Intake | Did it pick the right condition, donor and cell-type columns without being told? | `brief_updated` vs the known columns |
| Planner | Coverage of the paper's findings; variety; steps that name helpers and columns correctly | plan text vs the findings list |
| Coder | First-try success rate; most common errors (wrong column name, wrong helper key, wrong API) | `cell_finished` statuses and stderr |
| Reader | Does the summary quote numbers that appear in the output? | reader output vs cell stdout |
| Finding writer | Does every number in the claim appear in a printed output? | claim vs stdout |
| Critic | Verdict mix; how often the hard rules overrode it; revision requests that fixed the problem | `critic_notes` |
| Reporter | Overclaiming ("novel", "new") and use of `prior_analyses` | report text |

Proposed order: run Jäkel (fast) after each prompt change; run Schulte-Schrepping and Melms for the final benchmark table.
