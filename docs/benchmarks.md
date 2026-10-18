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

*(filled in from the runs below)*
