# Technical note

**Design.** A Google ADK orchestrator runs fixed control flow. A planner splits the ticket into tasks, Observability and Dependency specialists run them in parallel, then Reasoning ranks hypotheses, a Critic challenges them, and Reporting writes the answer. Agents share a typed blackboard, never free text. Critic objections become new tool tasks, so the feedback loop changes what runs next. Every loop and call is capped.

**Trust is enforced by code.** A claim counts as a FACT only if it quotes a real tool result; invented evidence is rejected and counted. An ANSWER needs enough confidence and a clear margin over rival causes; otherwise the report is INCONCLUSIVE.

**Data.** No incident is hand-written:
- 25 service-level scenarios, from a causal simulator.
- 8 message-level scenarios, from a simulator of a WhatsApp banking stack (webhook, SQS, Lambda worker, Redis, LLM, broker APIs) with a real git repo, CI and diffs.
- 4 RCAEval cases with real recorded telemetry.

Only `tests/eval/` reads the answer keys.

**Testing today.**
- 507 offline tests with a fake model.
- Golden tests replay recorded live runs exactly.
- A validator proves all 33 generated scenarios are solvable.
- Metamorphic variants (renamed services, shifted clocks, decoy deploys, deleted evidence) are generated and checked offline.
- Live runs: s01-s19, and selected v2 and RCAEval cases.

**Results (single runs).** After calibration both systems scored accuracy 0.83 on 12 v1 scenarios. The team cited all decisive evidence (the baseline 0.83 of it), and on the hold-out it never answered confidently wrong, where the baseline did twice. Both solved every v2 and RCAEval case tried.

**Four experiments**, on one v2 case and one RCAEval case:
1. **Parallel model calls, 4 vs 6.** With 4, one of five tasks waited about 3 minutes for a slot; 6 removes that wait and is the default.
2. **Sonnet only, no Opus.** Still correct. On a01, hallucinated evidence rose from 0 to 2% and decisive evidence cited fell from 1.0 to 0.67.
3. **Lean profile** (anomaly digests, shorter evidence). Combined with Sonnet-only it used 41% fewer tokens on RCAEval; alone, it saved about 2% on a01. On v1 it made the team confidently wrong twice, so it stays opt-in.
4. **Single agent vs team.** The single agent is 4-8x cheaper (50-70k tokens against 240-410k) and equally accurate here.

**Why this configuration.** Sonnet 5.5 runs the many tool-heavy steps, where speed matters. Opus 5.5 does the three judgement steps; without it, a01's report cited less decisive evidence and some unsupported evidence. Six agents are kept because the separate Critic and evidence ledger are what produce cited, calibrated answers and abstentions. The cost is tokens, mostly input.

**Limits.** Most data is synthetic. Samples are small and single-run. Adapters were tested against a local mock only. There is no API-key backend of our own and no front end.

**Further experiments** are recorded in `docs/RESULTS.md`.
