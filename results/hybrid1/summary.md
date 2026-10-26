## Summary

| system | runs | accuracy | weighted score | wrong (confident) | abstained | hallucinated evidence | decisive evidence cited | tool calls | LLM calls | tokens | latency s |
|---|---|---|---|---|---|---|---|---|---|---|---|
| hybrid | 2 | 0.5 | 0.5 | 0.0 | 0.5 | 0.0 | 1.0 | 27.5 | 17.5 | 121516 | 192.7 |

## Per scenario

| scenario | expected | hybrid |
|---|---|---|
| a01_broker_timeout | ANSWER | correct(+1.0) |
| s07_logs_vs_metrics | ANSWER | abstained(+0.0) |
