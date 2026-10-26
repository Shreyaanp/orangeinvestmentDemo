# s11_insufficient

World: v1 synthetic (service-level simulation). Expected outcome: **INCONCLUSIVE**.

## The ticket (all the agents are told)

> Portfolio pages are noticeably slower than usual since about 13:00. No errors reported by users.

Reported 2026-03-26 13:25 UTC.

## What the data holds (`data.json`)

- Window: 2026-03-26 12:00 to 14:00 UTC (120 min)
- Services (15): wa-webhook, orchestrator, llm-gateway, portfolio-svc, aa-sync, broker-gateway, order-router, market-data, auth-kyc, portfolio-consumer, msg-delivery, web-app, redis-cache, postgres, rabbitmq
- 2,312 log lines, 81 metric series, 4 changes, 3 past incidents
- 1 injected tool failures (the tools themselves flake)

| time (UTC) | kind | service | ref | note |
|---|---|---|---|---|
| 12:15 | deploy | postgres | postgres-00897 | dependency bump |
| 12:21 | deploy | web-app | web-app-00355 | metrics label rename |
| 12:40 | deploy | redis-cache | redis-cache-00897 | log level tweak |
| 12:57 | deploy | portfolio-svc | portfolio-svc-00712 | minor copy change |

## Answer key (spoiler, from `truth.json`; only `tests/eval/` reads it)

**F1 (primary)**: `portfolio-svc` / `thread_pool_starvation`, onset 13:00 UTC.

portfolio-svc ran out of request threads (thread pool saturation), slowing requests. Evidence for this is deliberately missing from the data.

Decisive evidence a correct report should cite:

- portfolio-svc: WARN logs containing `request thread pool saturated: 200/200 busy, queueing requests`, 13:00–14:00 UTC

## The trap

portfolio-svc logs are missing for the window; a deploy, a cache dip and a mild DB slowdown are all plausible

## Run it

```powershell
# offline, no tokens: replays the recorded run
$env:LLM_BACKEND="replay"; python -m eval.run --scenarios s11_insufficient --no-judge
# live (uses your Claude Code login)
$env:LLM_BACKEND="claude_code"; python -m eval.run --scenarios s11_insufficient --no-judge
```
