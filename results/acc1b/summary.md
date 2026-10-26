## Summary

| system | runs | accuracy | weighted score | wrong (confident) | abstained | hallucinated evidence | decisive evidence cited | tool calls | LLM calls | tokens | latency s |
|---|---|---|---|---|---|---|---|---|---|---|---|
| baseline | 9 | 0.889 | 0.889 | 0.0 | 0.111 | 0.0 | 0.944 | 17.111 | 5.778 | 51034 | 148.233 |
| multi | 9 | 0.889 | 0.889 | 0.0 | 0.111 | 0.01 | 1.0 | 50.222 | 37.333 | 434315 | 329.7 |

## Per scenario

| scenario | expected | baseline | multi |
|---|---|---|---|
| s01_bad_deploy | ANSWER | correct(+1.0) | correct(+1.0) |
| s02_pool_vs_deploy | ANSWER | correct(+1.0) | correct(+1.0) |
| s03_config_not_deploy | ANSWER | correct(+1.0) | correct(+1.0) |
| s05_poison_message | ANSWER | correct(+1.0) | correct(+1.0) |
| s06_clock_skew | ANSWER | correct(+1.0) | correct(+1.0) |
| s07_logs_vs_metrics | ANSWER | correct(+1.0) | abstained(+0.0) |
| s09_metrics_down | ANSWER | correct(+1.0) | correct(+1.0) |
| s10_truncated_logs | ANSWER | abstained(+0.0) | correct(+1.0) |
| s14_broker_partial | ANSWER | correct(+1.0) | correct(+1.0) |
