# Benchmarks

All numbers come from one NVIDIA H100 SXM (80 GB) running Nemotron 3.5 Lightning (NVFP4) on vLLM 0.27.1. Every generative call in every variant uses that one model.

Raw results, one JSON line per run:
- `bench/results/suite.jsonl`
- `bench/results/serving.jsonl`

To regenerate the summary tables:
```bash
uv run python -m bench.suite --report
uv run python -m bench.serving --report
```

## What we compare

| Variant | What it is |
| --- | --- |
| **multi** (SCRAP) | Planner, then hypotheses in parallel. Each step: coder (with error-driven retries), reader. Then finding writer, deterministic checks and a fresh-context statistics critic. |
| **no_critic** | The same hypotheses `multi` planned in that repeat, with the critic and the checks disabled. This isolates what the critic contributes. |
| **single** | One Lightning agent with the same data, the same tested helpers and the same brief, writing cells in one conversation (up to 15 cells). |

All variants get the same neutral goal for every dataset ("Characterize how the <tissue> differs between <condition> and healthy donors: gene programs within cell types and shifts in cell-type composition"). They get no hints about the papers' findings, and online literature search is off, so runs are comparable.

## Datasets

There are seven published case-control studies from CZ CELLxGENE, preprocessed identically (`bench/prepare_datasets.py`). Each paper's authors' own precomputed scores are removed first.

| Dataset | Tissue | Cells | Donors |
| --- | --- | --- | --- |
| Wilk et al. 2020, Nat Med | blood (COVID-19) | 44,649 | 13 |
| Schulte-Schrepping et al. 2020, Cell | blood (COVID-19) | 90,957 | 39 |
| Lee et al. 2020, Sci Immunol | blood (COVID-19) | 43,512 | 12 |
| Melms et al. 2021, Nature | lung, single-nucleus (lethal COVID-19) | 116,313 | 27 |
| Leng et al. 2021, Nat Neurosci | entorhinal cortex, single-nucleus (Alzheimer's) | 42,528 | 10 |
| Jäkel et al. 2019, Nature | white matter, single-nucleus (multiple sclerosis) | 17,799 | 9 |
| Sjögren's disease 2024 (preprint) | labial salivary gland | 83,384 | 25 |

## Scoring: recovery of published findings

`bench/datasets.json` lists **18 findings to recover**. Each was written from the paper's abstract (PMIDs listed there), as a topic and, where the abstract states one, a direction. For example, "HLA class II" with "lower".

A finding counts as **recovered** when the variant produced a claim that:
- was accepted (critic-approved; for variants without a critic, any claim counts);
- has an adjusted p-value below 0.05;
- matches the topic and the direction.

The rules are transparent keyword patterns, not an LLM judge. That makes them strict in one direction: a claim that recovers a finding in unusual wording can be missed. They never award a non-significant or rejected claim.

## Negative control: shuffled labels

`wilk_shuffled` is the Wilk dataset with the COVID-19/normal labels **permuted across donors** (`bench/shuffle_labels.py`):
- each new group mixes about half of each true group (4 true patients + 3 true controls labelled "COVID-19");
- columns that would reveal the true grouping are dropped (ventilation, admission, days since symptoms, …).

No real condition effect exists, so **every accepted significant finding is a false positive.**

## Serving

`bench/serving.py` runs the full system with 1, 2, 4 and 8 hypotheses in parallel on Wilk. It records:
- generated tokens/s;
- wall time and wall time per hypothesis;
- peak concurrent requests;
- per-call latency (p50 and p95);
- prefix-cache hit rate;
- speculative-decoding acceptance.

Each vLLM setup runs under its own label:
- `interactive`: DSpark speculative decoding, the default;
- `throughput`: no speculative decoding, larger batches.

## Results

Run on 2026-10-18: 8 datasets × 3 variants × 2 repeats, 5 hypotheses per run, 55 runs in total. Seven runs failed on a too-low JSON token cap and were redone after the fix. Per-run claims are in `bench/results/suite.jsonl`.

### 1. Negative control: no false discoveries

On `wilk_shuffled`, where no real condition effect exists:

| Variant | Claims made | Accepted, significant (= false positives) |
| --- | --- | --- |
| **multi (SCRAP)** | 6 | **0** (the critic rejected all 6) |
| no_critic | 5 | **0** |
| single agent | 18 | **14** |

**What the single agent did wrong.** Its false positives are genome-wide DESeq2 hits on single genes, run cell type by cell type: EHBP1-AS1, PLEKHH2, and the highly polymorphic HLA-DQB1, with adjusted p as low as 4e-6. With shuffled labels, these can only reflect donor-to-donor differences that happen to fall unevenly between the new groups. Reporting them as condition effects is exactly the failure a biologist gets burned by.

**Where SCRAP's 0 comes from.** It comes both from testing planned, pathway-level hypotheses and from the critic and checks: no_critic also reached 0, because its planned tests were not significant.

### 2. Recovery of published findings

| Dataset | Findings in paper | multi | no_critic | single |
| --- | --- | --- | --- | --- |
| COVID-19 PBMC (Wilk et al. 2020) | 3 | 1.0 | 1.0 | 0.5 |
| COVID-19 PBMC (Schulte-Schrepping et al. 2020) | 3 | 1.0 | 0.0 | 0.0 |
| COVID-19 PBMC (Lee et al. 2020) | 2 | 0.0 | 0.0 | 1.0 |
| Lethal COVID-19 lung (Melms et al. 2021) | 5 | 1.0 | 2.0 | 0.0 |
| Alzheimer's entorhinal cortex (Leng et al. 2021) | 2 | 0.0 | 0.5 | 1.0 |
| Multiple sclerosis white matter (Jäkel et al. 2019) | 1 | 0.0 | 0.0 | 0.5 |
| Sjögren's disease labial gland (2024) | 2 | 0.0 | 0.0 | 0.0 |
| **All 18 findings** | | **17%** | **19%** | **17%** |

The table shows the mean number recovered per run.

Across all runs, **8 of the 18 published findings were recovered at least once**:
- Wilk: the interferon-stimulated gene (ISG) signature;
- Schulte-Schrepping: the ISG signature in monocytes;
- Melms: macrophage infiltration, CTHRC1+ fibroblast expansion, and the alveolar type 2 (AT2) cell state;
- Lee: the TNF/IL-1β inflammatory response;
- Leng: reactive astrocytes;
- Jäkel: altered oligodendrocyte subpopulations.

**Reading:** with 5 hypotheses per run, every variant recovers about a sixth of the published findings, and the variants recover different ones. Breadth is limited by what the planner chooses to test, not by the statistics. Raising the number of hypotheses is cheap, because they run in parallel (see Serving). The multi-agent system's advantage on these datasets is **rigor and throughput, not recovery**.

### 3. Execution and efficiency (mean per run)

| Metric | multi | no_critic | single |
| --- | --- | --- | --- |
| Wall-clock (s) | 143 | 112 | 100 |
| LLM calls | 59 | 49 | 14 |
| Code cells / % that ran | 29 / 72% | 23 / 72% | 12 / 78% |
| **Generated tokens/s** | **966** | 997 | 166 |
| Peak concurrent requests | 5 | 4.7 | 1 |
| LLM latency p50 (s) | 4.5 | 4.6 | 2.5 |

Five parallel hypotheses produce **5.8× the token throughput** of a single agent on the same GPU, because vLLM batches their requests. Wall-clock grows only from 100 s to 143 s, while the system runs 4× the LLM calls and reviews every claim.

### Limits
- **The scoring is strict.** It uses keyword rules written from abstracts, not an expert or LLM judge. Correct recoveries phrased unusually are missed.
- **The runs are small.** Two repeats is enough to show direction, not to give tight intervals.
- **The datasets lack severity labels.** CELLxGENE versions of Schulte-Schrepping and Lee merge mild and severe COVID-19, but several of those papers' findings are severity-specific.
