# s18_missing_index

World: v1 synthetic (service-level simulation). Expected outcome: **ANSWER**.

## The ticket (all the agents are told)

> Portfolio pages and syncs are slow or timing out since about 10:40. Connection pool alerts are firing.

Reported 2026-04-06 11:05 UTC.

## What the data holds (`data.json`)

- Window: 2026-04-06 09:40 to 11:40 UTC (120 min)
- Services (15): wa-webhook, orchestrator, llm-gateway, portfolio-svc, aa-sync, broker-gateway, order-router, market-data, auth-kyc, portfolio-consumer, msg-delivery, web-app, redis-cache, postgres, rabbitmq
- 2,873 log lines, 81 metric series, 4 changes, 3 past incidents

| time (UTC) | kind | service | ref | note |
|---|---|---|---|---|
| 10:39 | migration | postgres | mig-20260406-0042 | rebuild holdings table; indexes not recreated |
| 11:05 | deploy | redis-cache | redis-cache-00509 | metrics label rename |
| 11:21 | deploy | orchestrator | orchestrator-00544 | minor copy change |
| 11:34 | deploy | web-app | web-app-00299 | log level tweak |

## Answer key (spoiler, from `truth.json`; only `tests/eval/` reads it)

**F1 (primary)**: `postgres` / `missing_index_after_migration`, onset 10:40 UTC.

A database migration rebuilt the holdings table without recreating its indexes, so queries do sequential scans and slow down; connection-pool exhaustion is a consequence.

Decisive evidence a correct report should cite:

- postgres: WARN logs containing `slow query: seq scan on holdings took`, 10:40–11:40 UTC
- postgres: the change whose ref contains `mig-20260406-0042`, 10:39–11:40 UTC

## The trap

pool exhaustion in aa-sync looks like the cause but is an effect; the trigger was a migration, not a service deploy

## Run it

```powershell
# offline, no tokens: replays the recorded run
$env:LLM_BACKEND="replay"; python -m eval.run --scenarios s18_missing_index --no-judge
# live (uses your Claude Code login)
$env:LLM_BACKEND="claude_code"; python -m eval.run --scenarios s18_missing_index --no-judge
```
