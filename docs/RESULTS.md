# Results

Every table comes from the score files named under its heading (the v1 tables via
`python -m eval.report`). Weighted score: correct +1, partial +0.5, confidently wrong -1, abstained
0; on an unanswerable scenario (s11, f06, a08), abstaining is +1 and answering is -1. Accuracy counts correct as 1 and partial as 0.5. "Decisive
evidence cited" is the share of the answer key's decisive evidence the report actually cites.
Runs are single samples per scenario and system unless stated: treat small differences as noise.

## Development set s01-s13 (default profile, re-judged)

Thresholds were calibrated on these scenarios, so this is the optimistic view. Dev-set runs happened before calibration; judge re-scored afterwards. The s12 numbers are pre-repair (its data changed in accuracy round 1).

Source: `results/full1/rescored.jsonl` (25 runs)

| system | runs | accuracy | weighted score | wrong (confident) | abstained | hallucinated evidence | decisive evidence cited | tool calls | LLM calls | tokens | latency s |
|---|---|---|---|---|---|---|---|---|---|---|---|
| baseline | 13 | 0.923 | 0.923 | 0.0 | 0.077 | 0.0 | 0.75 | 17.846 | 6.077 | 46481 | 117.292 |
| multi | 12 | 0.583 | 0.417 | 0.167 | 0.25 | 0.019 | 1.0 | 52.333 | 37.0 | 439196 | 342.242 |

| scenario | expected | baseline | multi |
|---|---|---|---|
| s01_bad_deploy | ANSWER | correct(+1.0) | correct(+1.0) |
| s02_pool_vs_deploy | ANSWER | correct(+1.0) | abstained(+0.0) |
| s03_config_not_deploy | ANSWER | correct(+1.0) | correct(+1.0) |
| s04_queue_backlog | ANSWER | correct(+1.0) | correct(+1.0) |
| s05_poison_message | ANSWER | correct(+1.0) | abstained(+0.0) |
| s06_clock_skew | ANSWER | correct(+1.0) | correct(+1.0) |
| s07_logs_vs_metrics | ANSWER | correct(+1.0) | wrong(-1.0) |
| s08_stale_history | ANSWER | correct(+1.0) | correct(+1.0) |
| s09_metrics_down | ANSWER | abstained(+0.0) | wrong(-1.0) |
| s10_truncated_logs | ANSWER | correct(+1.0) | correct(+1.0) |
| s11_insufficient | INCONCLUSIVE | correct(+1.0) | correct(+1.0) |
| s12_two_causes | ANSWER | correct(+1.0) | abstained(+0.0) |
| s13_stale_balance | ANSWER | correct(+1.0) | - |

## Hold-out s02 s13-s19 (default profile, calibrated thresholds, re-judged; PRE-REPAIR)

Scenarios s13-s19 were never seen during calibration; s02 is a repeat of a development scenario. This is the fairer test. Pre-repair: s17 and s19 data were changed afterwards (accuracy round 1), and these runs predate the uncorroborated split, so s02/s14/s17/s19 here are not comparable with the accuracy round 1 table below.

Source: `results/full2/rescored.jsonl` (16 runs)

| system | runs | accuracy | weighted score | wrong (confident) | abstained | hallucinated evidence | decisive evidence cited | tool calls | LLM calls | tokens | latency s |
|---|---|---|---|---|---|---|---|---|---|---|---|
| baseline | 8 | 0.75 | 0.5 | 0.25 | 0.0 | 0.0 | 0.854 | 15.625 | 5.5 | 40912 | 115.0 |
| multi | 8 | 0.625 | 0.625 | 0.0 | 0.375 | 0.008 | 0.917 | 49.25 | 37.5 | 422457 | 327.325 |

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

## Lean profile A/B (opt-in), s01 s05 s12 s14 s17 s19 (PRE-REPAIR)

Single runs; opt-in digest tools. Ran on the pre-repair s12/s17/s19 data.

Source: `results/lean1/scores.jsonl` (12 runs)

| system | runs | accuracy | weighted score | wrong (confident) | abstained | hallucinated evidence | decisive evidence cited | tool calls | LLM calls | tokens | latency s |
|---|---|---|---|---|---|---|---|---|---|---|---|
| baseline | 6 | 1.0 | 1.0 | 0.0 | 0.0 | 0.0 | 0.945 | 8.667 | 5.0 | 35713 | 75.9 |
| multi | 6 | 0.5 | 0.167 | 0.333 | 0.167 | 0.014 | 0.958 | 46.833 | 41.833 | 360603 | 323.117 |

| scenario | expected | baseline | multi |
|---|---|---|---|
| s01_bad_deploy | ANSWER | correct(+1.0) | correct(+1.0) |
| s05_poison_message | ANSWER | correct(+1.0) | correct(+1.0) |
| s12_two_causes | ANSWER | correct(+1.0) | correct(+1.0) |
| s14_broker_partial | ANSWER | correct(+1.0) | wrong(-1.0) |
| s17_retry_storm | ANSWER | correct(+1.0) | wrong(-1.0) |
| s19_duplicate_orders | ANSWER | correct(+1.0) | abstained(+0.0) |

## Accuracy round 1 (default profile, uncorroborated split + s12/s17/s19 repairs, re-judged)

Hypotheses HA-HD were written down before these runs. Single runs per cell. Compared with the latest earlier default-profile run of each scenario, multi-agent goes from 5 correct / 5 abstained / 2 confidently wrong to 10 / 1 / 1; the baseline stays at 10 correct (gains s09, s14; loses s10 to an abstention; still wrong on s17). Not a clean hold-out: s12, s17, s19 were repaired after I saw them fail, s02/s05/s14 had been seen too. Did not work: s17 is now confidently wrong for both systems (they blame the recovered broker blip, not the retry storm), and s07 still does not reach ANSWER for multi-agent (abstained instead of wrong).

Source: `results/acc1/rescored.jsonl` (24 runs)

| system | runs | accuracy | weighted score | wrong (confident) | abstained | hallucinated evidence | decisive evidence cited | tool calls | LLM calls | tokens | latency s |
|---|---|---|---|---|---|---|---|---|---|---|---|
| baseline | 12 | 0.833 | 0.75 | 0.083 | 0.083 | 0.0 | 0.831 | 17.25 | 5.833 | 51886 | 140.508 |
| multi | 12 | 0.833 | 0.75 | 0.083 | 0.083 | 0.008 | 1.0 | 50.417 | 37.667 | 434349 | 321.508 |

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
| s12_two_causes | ANSWER | correct(+1.0) | correct(+1.0) |
| s14_broker_partial | ANSWER | correct(+1.0) | correct(+1.0) |
| s17_retry_storm | ANSWER | wrong(-1.0) | wrong(-1.0) |
| s19_duplicate_orders | ANSWER | correct(+1.0) | correct(+1.0) |

## v2 app world and RCAEval: cost and model experiment (2026-10-26)

One live run per cell, no judge, so read as directional. Sonnet 5.5 and Opus 5.5 both at medium
effort. Sources: `results/v2demo/scores.jsonl` (first row), `results/exp_*/scores.jsonl` (the rest).

| case | system / setup | outcome | tokens | latency s | hallucinated evidence | decisive evidence cited |
|---|---|---|---|---|---|---|
| a01_broker_timeout | multi, Sonnet + Opus, 4 parallel calls | correct | 237,823 | 487 | 0 | 1.0 |
| a01_broker_timeout | multi, Sonnet only, 6 parallel | correct | 272,989 | 175 | 0.02 | 0.67 |
| a01_broker_timeout | multi, lean + Sonnet only | correct | 268,479 | 341 | 0 | 1.0 |
| a01_broker_timeout | baseline (Opus) | correct | 52,448 | 88 | 0 | 0.33 |
| rca_re2ob_checkoutservice_cpu_1 | multi, Sonnet + Opus, 6 parallel | correct | 406,035 | 248 | 0.05 | 1.0 |
| rca_re2ob_checkoutservice_cpu_1 | multi, lean + Sonnet only | correct | 238,421 | 151 | 0.07 | 1.0 |
| rca_re2ob_checkoutservice_cpu_1 | baseline (Opus) | correct | 67,702 | 103 | 0 | 1.0 |

Every configuration found the cause. Latency is model time, not code: with 4 parallel slots one of the
five round-1 tasks queued for about 3 minutes; 6 slots remove that wait (now the default). The
175 s a01 run also used Sonnet only, so it does not isolate the effect of parallelism. Removing Opus kept the answers right; on a01, the one clean comparison, hallucinated evidence
rose from 0 to 0.02 and decisive evidence cited fell to 0.67. Lean plus Sonnet-only used 41% fewer
tokens on RCAEval (two changes at once); lean alone saved about 2% on a01. The single agent stayed 4-8x cheaper.

## Hybrid: one investigator, then the team's checks (2026-10-26)

`--systems hybrid` (`src/incident/hybrid.py`) runs the single agent with full context, grounds its
evidence and scores it with the same code, then the Critic reviews once; objections become parallel
specialist tasks and Reasoning re-ranks (one verification round at most). One live run per cell.
Sources: `results/hybrid1*/scores.jsonl`; baseline and multi rows as in the tables above (s07 from
`results/acc1/rescored.jsonl`).

| case | baseline | multi | hybrid |
|---|---|---|---|
| a01_broker_timeout | correct, 52k tokens, 88 s | correct, 238k, 487 s | correct, 144k, 219 s |
| rca_re2ob_checkoutservice_cpu_1 | correct, 68k, 103 s | correct, 406k, 248 s | correct, 142k, 227 s (hallucinated evidence 0.07) |
| s07_logs_vs_metrics | correct, 72k, 273 s | abstained, 514k, 401 s | abstained, 99k, 167 s |

The hybrid used 35-80% fewer tokens than the team and cited all decisive evidence in every case.
On s07 the investigator's leading cause was a stall inside market-data. The answer key says the
upstream feed stalled, which was the investigator's second hypothesis. The Critic asked which it
was, the follow-up checks could not separate the two, and the system abstained. Three runs do not
show the hybrid is better than either system; they show it keeps the team's checks at about half
its cost.

## Knowledge base and memory: live test (opt-in features)

Scenarios s01, s05 and s14 with every clock time shifted, so a past occurrence is a recurrence,
not an identical report. One live run per cell. The "with" arm gives the system catalogue plus
incident memory built from other scenarios' saved reports. These numbers were recovered from the
run log; the per-run files were not kept.

| arm | system | correct of 3 | tool calls | LLM calls | tokens | latency s |
|---|---|---|---|---|---|---|
| no knowledge | baseline | 3 | 14.0 | 6.0 | 42,483 | 97 |
| no knowledge | multi | 2 (s14 abstained) | 40.7 | 24.7 | 224,178 | 334 |
| memory + catalogue | baseline | 3 | 17.0 | 6.3 | 56,540 | 90 |
| memory + catalogue | multi | 3 | 33.7 | 19.7 | 239,329 | 164 |

For the multi-agent team, memory and the catalogue added one correct answer and cut tool calls by
17% and wall time by about half, at 7% more tokens. The baseline was already 3 of 3. The sample is
small and the two features were switched on together, so this is directional, and their separate
effects are not measured. A misleading look-alike memory was not tested live; offline tests show it
cannot change the status or the confidence.

## Real telemetry: RCAEval

To check the system outside our own simulators, we imported four cases from
[RCAEval](https://huggingface.co/datasets/phamquiluan/RCAEval), a public root-cause-analysis
benchmark. All four come from the RE2 suite, which runs the Online Boutique microservices demo and
injects a known fault while recording real metrics and logs.

| case | injected fault (answer key) | data | run live |
|---|---|---|---|
| rca_re2ob_checkoutservice_cpu_1 | CPU saturation in checkoutservice | 17,132 log lines, 72 metric series | yes, 4 configurations |
| rca_re2ob_currencyservice_delay_1 | network delay in currencyservice | 16,122 log lines, 76 metric series | not yet |
| rca_re2ob_emailservice_mem_1 | memory exhaustion in emailservice | 17,738 log lines, 71 metric series | not yet |
| rca_re2ob_productcatalogservice_loss_1 | packet loss in productcatalogservice | 11,974 log lines, 72 metric series | not yet |

**Why it is a harder test.** The ticket is the same generic sentence for every case: "Shop users
report slow pages and some failed requests since about HH:MM UTC." It names no service. The cases
have 12 services, 25 minutes of data, **no deploys or config changes** and no past incidents, so
there is no recent change to blame. The cause has to be found from metrics and logs alone. We did
not generate this data. `src/scripts/import_rcaeval.py` converts it the same way for every case: it
averages per-second metrics per minute, infers log levels from the message text, and keeps every
warning and error line.

**Results on the checkout CPU case.** One live run per configuration, scored against the
benchmark's own label:

| system | outcome | tokens | latency s | hallucinated evidence | decisive evidence cited |
|---|---|---|---|---|---|
| single-agent baseline (Opus) | correct | 67,702 | 103 | 0 | 1.0 |
| multi-agent team (Sonnet + Opus) | correct | 406,035 | 248 | 0.05 | 1.0 |
| multi-agent, lean + Sonnet only | correct | 238,421 | 151 | 0.07 | 1.0 |
| hybrid (one investigator + Critic) | correct | 142,036 | 227 | 0.07 | 1.0 |

Every configuration named checkoutservice and a CPU cause, and cited the decisive CPU metric. On
real data the team needed 3 rounds and hit the 70-tool-call cap before answering; the baseline
answered in one pass at about a sixth of the tokens.

**Limits.** This is one live case, not a benchmark score. The other three cases have been
imported, and the importer is covered by offline tests, but they have not been run live. Traces
from RCAEval are not used, because our tools have no trace query. Sources:
`results/exp_rca_*/scores.jsonl` and `results/hybrid1_rca/scores.jsonl`. Replay the multi-agent run
offline with `python -m eval.demo rca_re2ob_checkoutservice_cpu_1`.
