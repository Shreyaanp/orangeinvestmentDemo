# s02_pool_vs_deploy

World: v1 synthetic (service-level simulation). Expected outcome: **ANSWER**.

## The ticket (all the agents are told)

> Users report that portfolio balances look stale or fail to refresh since about 12:55. Sync errors are spiking.

Reported 2026-03-14 13:25 UTC.

## What the data holds (`data.json`)

- Window: 2026-03-14 12:00 to 14:00 UTC (120 min)
- Services (15): wa-webhook, orchestrator, llm-gateway, portfolio-svc, aa-sync, broker-gateway, order-router, market-data, auth-kyc, portfolio-consumer, msg-delivery, web-app, redis-cache, postgres, rabbitmq
- 3,239 log lines, 81 metric series, 4 changes, 3 past incidents

| time (UTC) | kind | service | ref | note |
|---|---|---|---|---|
| 12:25 | deploy | auth-kyc | auth-kyc-00453 | log level tweak |
| 13:00 | deploy | web-app | web-app-00231 | UI copy change on holdings page |
| 13:20 | deploy | market-data | market-data-00374 | log level tweak |
| 13:47 | deploy | orchestrator | orchestrator-00740 | minor copy change |

## Answer key (spoiler, from `truth.json`; only `tests/eval/` reads it)

**F1 (primary)**: `aa-sync` / `db_pool_exhaustion`, onset 12:50 UTC.

aa-sync exhausted its database connection pool (pool full, requests queued), making account-aggregator sync slow and error-prone and leaving portfolio data stale.

Decisive evidence a correct report should cite:

- aa-sync: ERROR logs containing `connection pool exhausted:`, 12:56–14:00 UTC
- aa-sync: WARN logs containing `slow query on holdings_snapshot took`, 12:50–14:00 UTC

## The trap

unrelated UI deploy 10 minutes after the real onset

## Run it

```powershell
# offline, no tokens: replays the recorded run
$env:LLM_BACKEND="replay"; python -m eval.run --scenarios s02_pool_vs_deploy --no-judge
# live (uses your Claude Code login)
$env:LLM_BACKEND="claude_code"; python -m eval.run --scenarios s02_pool_vs_deploy --no-judge
```
