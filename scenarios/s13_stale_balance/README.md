# s13_stale_balance

World: v1 synthetic (service-level simulation). Expected outcome: **ANSWER**.

## The ticket (all the agents are told)

> Users say their balances are out of date: trades made more than ten minutes ago do not show up.

Reported 2026-03-30 12:30 UTC.

## What the data holds (`data.json`)

- Window: 2026-03-30 11:00 to 13:00 UTC (120 min)
- Services (15): wa-webhook, orchestrator, llm-gateway, portfolio-svc, aa-sync, broker-gateway, order-router, market-data, auth-kyc, portfolio-consumer, msg-delivery, web-app, redis-cache, postgres, rabbitmq
- 2,388 log lines, 82 metric series, 4 changes, 3 past incidents

| time (UTC) | kind | service | ref | note |
|---|---|---|---|---|
| 11:19 | deploy | market-data | market-data-00813 | dependency bump |
| 11:20 | deploy | llm-gateway | llm-gateway-00900 | metrics label rename |
| 11:27 | deploy | broker-gateway | broker-gateway-00883 | log level tweak |
| 12:00 | config | portfolio-svc | cfg-holdings-cache-ttl | HOLDINGS_CACHE_TTL_S 60 -> 1800 |

## Answer key (spoiler, from `truth.json`; only `tests/eval/` reads it)

**F1 (primary)**: `portfolio-svc` / `stale_cache_ttl_config`, onset 12:00 UTC.

A configuration change raised portfolio-svc's holdings cache TTL (60s to 1800s), so users see stale cached balances.

Decisive evidence a correct report should cite:

- portfolio-svc: INFO logs containing `serving holdings from cache, entry age`, 12:00–13:00 UTC
- portfolio-svc: the change whose ref contains `cfg-holdings-cache-ttl`, 12:00–13:00 UTC
- portfolio-svc: metric `cache_staleness_s` at or above 1440.0, 12:00–13:00 UTC

## The trap

aa-sync is slightly slow at the same time but that is not why balances are stale

## Run it

```powershell
# offline, no tokens: replays the recorded run
$env:LLM_BACKEND="replay"; python -m eval.run --scenarios s13_stale_balance --no-judge
# live (uses your Claude Code login)
$env:LLM_BACKEND="claude_code"; python -m eval.run --scenarios s13_stale_balance --no-judge
```
