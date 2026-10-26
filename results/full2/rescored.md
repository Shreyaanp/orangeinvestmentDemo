## Summary (re-scored)

| system | runs | accuracy | weighted score | wrong (confident) | abstained | hallucinated evidence | decisive evidence cited | tool calls | LLM calls | tokens | latency s |
|---|---|---|---|---|---|---|---|---|---|---|---|
| baseline | 8 | 0.75 | 0.5 | 0.25 | 0.0 | 0.0 | 0.854 | 15.625 | 5.5 | 40912 | 115.0 |
| multi | 8 | 0.625 | 0.625 | 0.0 | 0.375 | 0.008 | 0.917 | 49.25 | 37.5 | 422457 | 327.325 |

## Per scenario

| scenario | expected | baseline | multi |
|---|---|---|---|
| s02_pool_vs_deploy | ANSWER | correct(+1.0) | correct(+1.0) |
| s13_stale_balance | ANSWER | correct(+1.0) | correct(+1.0) |
| s14_broker_partial | ANSWER | wrong(-1.0) | abstained(+0.0) |
| s15_rebalance_storm | ANSWER | correct(+1.0) | correct(+1.0) |
| s16_schema_dlq | ANSWER | correct(+1.0) | correct(+1.0) |
| s17_retry_storm | ANSWER | wrong(-1.0) | abstained(+0.0) |
| s18_missing_index | ANSWER | correct(+1.0) | correct(+1.0) |
| s19_duplicate_orders | ANSWER | correct(+1.0) | abstained(+0.0) |
