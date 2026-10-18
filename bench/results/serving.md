## Serving: parallel hypotheses on one H100

| Setup | Parallel hypotheses | Wall (s) | Wall per hypothesis (s) | Generated tokens/s | Peak concurrent requests | LLM latency p50 / p95 (s) | Prefix cache hit (%) | Spec. decoding acceptance (%) | Accepted findings |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| interactive | 1 | 56 | 56 | 322 | 1 | 2.7 / 7.1 | 4.6 | 68.7 | 1 / 1 |
| interactive | 2 | 90 | 45 | 621 | 2 | 3.0 / 11.7 | 2.1 | 68.0 | 1 / 2 |
| interactive | 4 | 116 | 29 | 1072 | 4 | 3.5 / 19.1 | 4.8 | 67.1 | 1 / 4 |
| interactive | 8 | 199 | 25 | 992 | 6 | 5.5 / 32.0 | 10.7 | 66.3 | 3 / 6 |
| throughput | 1 | 99 | 99 | 268 | 1 | 4.2 / 23.8 | 47.9 | 0.0 | 1 / 1 |
| throughput | 4 | 198 | 49 | 492 | 4 | 8.2 / 32.5 | 53.1 | 0.0 | 1 / 4 |
| throughput | 8 | 298 | 37 | 803 | 8 | 10.4 / 42.0 | 53.5 | 0.0 | 6 / 8 |

Mean generated tokens/s per setup: interactive 752, throughput 521
