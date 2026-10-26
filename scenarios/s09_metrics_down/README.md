# s09_metrics_down

World: v1 synthetic (service-level simulation). Expected outcome: **ANSWER**.

## The ticket (all the agents are told)

> Portfolio pages and the assistant's balance answers are very slow since about 15:10.

Reported 2026-03-24 15:20 UTC.

## What the data holds (`data.json`)

- Window: 2026-03-24 14:00 to 16:00 UTC (120 min)
- Services (15): wa-webhook, orchestrator, llm-gateway, portfolio-svc, aa-sync, broker-gateway, order-router, market-data, auth-kyc, portfolio-consumer, msg-delivery, web-app, redis-cache, postgres, rabbitmq
- 2,583 log lines, 81 metric series, 3 changes, 3 past incidents
- 2 injected tool failures (the tools themselves flake)

| time (UTC) | kind | service | ref | note |
|---|---|---|---|---|
| 14:09 | deploy | postgres | postgres-00591 | metrics label rename |
| 14:12 | deploy | broker-gateway | broker-gateway-00870 | metrics label rename |
| 14:27 | deploy | msg-delivery | msg-delivery-00675 | log level tweak |

## Answer key (spoiler, from `truth.json`; only `tests/eval/` reads it)

**F1 (primary)**: `redis-cache` / `cache_stampede`, onset 15:10 UTC.

A cache stampede on redis-cache after a burst of hot-key TTL expiry: the hit ratio collapsed, load fell on postgres, and portfolio-svc slowed.

Decisive evidence a correct report should cite:

- redis-cache: WARN logs containing `ttl expiry burst:`, 15:10–15:45 UTC

## The trap

the metrics tool times out on the first two calls and returns partial data on the next two

## Run it

```powershell
# offline, no tokens: replays the recorded run
$env:LLM_BACKEND="replay"; python -m eval.run --scenarios s09_metrics_down --no-judge
# live (uses your Claude Code login)
$env:LLM_BACKEND="claude_code"; python -m eval.run --scenarios s09_metrics_down --no-judge
```
