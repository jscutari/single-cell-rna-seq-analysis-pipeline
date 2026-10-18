## Recovery of published findings (mean over repeats)

| Dataset | Findings in paper | multi | no_critic | single |
| --- | --- | --- | --- | --- |
| COVID-19 PBMC (Wilk et al. 2020) | 3 | 1.0 / 3 (n=2) | 1.0 / 3 (n=2) | 0.5 / 3 (n=2) |
| COVID-19 PBMC (Schulte-Schrepping et al. 2020) | 3 | 1.0 / 3 (n=2) | 0.0 / 3 (n=2) | 0.0 / 3 (n=2) |
| COVID-19 PBMC (Lee et al. 2020) | 2 | 0.0 / 2 (n=2) | 0.0 / 2 (n=2) | 1.0 / 2 (n=2) |
| Lethal COVID-19 lung (Melms et al. 2021) | 5 | 1.0 / 5 (n=2) | 2.0 / 5 (n=2) | 0.0 / 5 (n=2) |
| Alzheimer's entorhinal cortex (Leng et al. 2021) | 2 | 0.0 / 2 (n=2) | 0.5 / 2 (n=2) | 1.0 / 2 (n=2) |
| Multiple sclerosis white matter (Jäkel et al. 2019) | 1 | 0.0 / 1 (n=2) | 0.0 / 1 (n=2) | 0.5 / 1 (n=2) |
| Sjögren's disease labial gland (2023) | 2 | 0.0 / 2 (n=2) | 0.0 / 2 (n=2) | 0.0 / 2 (n=2) |
| **All datasets** | | **17%** | **19%** | **17%** |

## Negative control: shuffled condition labels (no real difference exists)

| Variant | Runs | Hypotheses tested | Accepted (false positives) | Rejected by critic |
| --- | --- | --- | --- | --- |
| multi | 2 | 6 | **0** | 6 |
| no_critic | 2 | 5 | **0** | 0 |
| single | 2 | 18 | **14** | 0 |

## Execution and efficiency (mean per run, all datasets)

| Metric | multi | no_critic | single |
| --- | --- | --- | --- |
| Wall-clock (s) | 143 | 112 | 100 |
| LLM calls | 59 | 49 | 14 |
| Code cells | 29 | 23 | 12 |
| Cells that ran (%) | 72 | 72 | 78 |
| Generated tokens/s | 966 | 997 | 166 |
| Peak concurrent requests | 5.0 | 4.7 | 1.0 |
| LLM latency p50 (s) | 4.5 | 4.6 | 2.5 |
| Accepted findings | 1.1 | 1.0 | 1.9 |
