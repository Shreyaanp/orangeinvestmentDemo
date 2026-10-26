## Summary

| system | runs | accuracy | weighted score | wrong (confident) | abstained | hallucinated evidence | decisive evidence cited | tool calls | LLM calls | tokens | latency s |
|---|---|---|---|---|---|---|---|---|---|---|---|
| baseline | 6 | 1.0 | 1.0 | 0.0 | 0.0 | 0.0 | 0.945 | 8.667 | 5.0 | 35713 | 75.9 |
| multi | 6 | 0.5 | 0.167 | 0.333 | 0.167 | 0.014 | 0.958 | 46.833 | 41.833 | 360603 | 323.117 |

## Per scenario

| scenario | expected | baseline | multi |
|---|---|---|---|
| s01_bad_deploy | ANSWER | correct(+1.0) | correct(+1.0) |
| s05_poison_message | ANSWER | correct(+1.0) | correct(+1.0) |
| s12_two_causes | ANSWER | correct(+1.0) | correct(+1.0) |
| s14_broker_partial | ANSWER | correct(+1.0) | wrong(-1.0) |
| s17_retry_storm | ANSWER | correct(+1.0) | wrong(-1.0) |
| s19_duplicate_orders | ANSWER | correct(+1.0) | abstained(+0.0) |
