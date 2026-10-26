# f03_replica_lag

World: v1 synthetic (service-level simulation). Expected outcome: **ANSWER**.

## The ticket (all the agents are told)

> Customers say their portfolio balance does not reflect trades they just made; it catches up minutes later. Started around 10:00.

Reported 2026-05-08 10:25 UTC.

## What the data holds (`data.json`)

- Window: 2026-05-08 09:00 to 11:00 UTC (120 min)
- Services (15): wa-webhook, orchestrator, llm-gateway, portfolio-svc, aa-sync, broker-gateway, order-router, market-data, auth-kyc, portfolio-consumer, msg-delivery, web-app, redis-cache, postgres, rabbitmq
- 2,604 log lines, 81 metric series, 4 changes, 4 past incidents

| time (UTC) | kind | service | ref | note |
|---|---|---|---|---|
| 09:25 | migration | postgres | mig-0142 | create index concurrently on trades(user_id) |
| 09:29 | deploy | orchestrator | orchestrator-00827 | metrics label rename |
| 09:29 | deploy | postgres | postgres-00794 | metrics label rename |
| 10:45 | deploy | redis-cache | redis-cache-00991 | dependency bump |

## Answer key (spoiler, from `truth.json`; only `tests/eval/` reads it)

**F1 (primary)**: `postgres` / `read_replica_lag`, onset 09:58 UTC.

The postgres read replica fell minutes behind the primary (replication lag), so portfolio reads served from it return holdings that predate recent trades.

Decisive evidence a correct report should cite:

- postgres: WARN logs containing `replica pg-replica-1 apply lag`, 09:58–11:00 UTC

## The trap

a past incident with the same symptom blamed the cache; a postgres migration ran earlier and finished cleanly

## Run it

```powershell
# live (uses your Claude Code login)
$env:LLM_BACKEND="claude_code"; python -m eval.run --scenarios f03_replica_lag --no-judge
```
