## Summary

| system | runs | accuracy | weighted score | wrong (confident) | abstained | hallucinated evidence | decisive evidence cited | tool calls | LLM calls | tokens | latency s |
|---|---|---|---|---|---|---|---|---|---|---|---|
| baseline | 3 | 0.667 | 0.333 | 0.333 | 0.0 | 0.0 | 0.489 | 17.667 | 6.0 | 54441 | 117.333 |
| multi | 3 | 0.667 | 0.333 | 0.333 | 0.0 | 0.003 | 1.0 | 51.0 | 38.667 | 434451 | 296.933 |

## Per scenario

| scenario | expected | baseline | multi |
|---|---|---|---|
| s12_two_causes | ANSWER | correct(+1.0) | correct(+1.0) |
| s17_retry_storm | ANSWER | wrong(-1.0) | wrong(-1.0) |
| s19_duplicate_orders | ANSWER | correct(+1.0) | correct(+1.0) |
