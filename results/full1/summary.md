## Summary

| system | runs | accuracy | weighted score | wrong (confident) | abstained | hallucinated evidence | decisive evidence cited | tool calls | LLM calls | tokens | latency s |
|---|---|---|---|---|---|---|---|---|---|---|---|
| baseline | 13 | 0.731 | 0.577 | 0.154 | 0.077 | 0.0 | 0.75 | 17.846 | 6.077 | 46481 | 117.292 |
| multi | 12 | 0.583 | 0.417 | 0.167 | 0.25 | 0.019 | 1.0 | 52.333 | 37.0 | 439196 | 342.242 |

## Per scenario

| scenario | expected | baseline | multi |
|---|---|---|---|
| s01_bad_deploy | ANSWER | correct(+1.0) | correct(+1.0) |
| s02_pool_vs_deploy | ANSWER | correct(+1.0) | abstained(+0.0) |
| s03_config_not_deploy | ANSWER | correct(+1.0) | correct(+1.0) |
| s04_queue_backlog | ANSWER | correct(+1.0) | correct(+1.0) |
| s05_poison_message | ANSWER | wrong(-1.0) | abstained(+0.0) |
| s06_clock_skew | ANSWER | correct(+1.0) | correct(+1.0) |
| s07_logs_vs_metrics | ANSWER | correct(+1.0) | wrong(-1.0) |
| s08_stale_history | ANSWER | correct(+1.0) | correct(+1.0) |
| s09_metrics_down | ANSWER | abstained(+0.0) | wrong(-1.0) |
| s10_truncated_logs | ANSWER | wrong(-1.0) | correct(+1.0) |
| s11_insufficient | INCONCLUSIVE | correct(+1.0) | correct(+1.0) |
| s12_two_causes | ANSWER | partial(+0.5) | abstained(+0.0) |
| s13_stale_balance | ANSWER | correct(+1.0) | - |
