# s04_queue_backlog

World: v1 synthetic (service-level simulation). Expected outcome: **ANSWER**.

## The ticket (all the agents are told)

> Users are receiving portfolio-update notifications hours late, and some have not arrived at all today.

Reported 2026-03-17 10:40 UTC.

## What the data holds (`data.json`)

- Window: 2026-03-17 09:00 to 11:00 UTC (120 min)
- Services (15): wa-webhook, orchestrator, llm-gateway, portfolio-svc, aa-sync, broker-gateway, order-router, market-data, auth-kyc, portfolio-consumer, msg-delivery, web-app, redis-cache, postgres, rabbitmq
- 2,708 log lines, 81 metric series, 3 changes, 3 past incidents

| time (UTC) | kind | service | ref | note |
|---|---|---|---|---|
| 09:11 | deploy | broker-gateway | broker-gateway-00408 | log level tweak |
| 09:23 | deploy | redis-cache | redis-cache-00610 | log level tweak |
| 09:32 | deploy | orchestrator | orchestrator-00311 | log level tweak |

## Answer key (spoiler, from `truth.json`; only `tests/eval/` reads it)

**F1 (primary)**: `aa-sync` / `cpu_throttling`, onset 09:55 UTC.

aa-sync was CPU-throttled so its latency rose several-fold; the downstream consumer slowed and the portfolio-updates queue backed up, delaying notifications.

Decisive evidence a correct report should cite:

- aa-sync: WARN logs containing `request processing slow: p95`, 09:55–11:00 UTC

## The trap

benign broker memory alarm earlier in the window, already cleared

## Run it

```powershell
# offline, no tokens: replays the recorded run
$env:LLM_BACKEND="replay"; python -m eval.run --scenarios s04_queue_backlog --no-judge
# live (uses your Claude Code login)
$env:LLM_BACKEND="claude_code"; python -m eval.run --scenarios s04_queue_backlog --no-judge
```
