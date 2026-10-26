# s19_duplicate_orders

World: v1 synthetic (service-level simulation). Expected outcome: **ANSWER**.

## The ticket (all the agents are told)

> Several customers report that one WhatsApp order message resulted in two executed orders around 14:10.

Reported 2026-04-07 14:40 UTC.

## What the data holds (`data.json`)

- Window: 2026-04-07 13:10 to 15:10 UTC (120 min)
- Services (15): wa-webhook, orchestrator, llm-gateway, portfolio-svc, aa-sync, broker-gateway, order-router, market-data, auth-kyc, portfolio-consumer, msg-delivery, web-app, redis-cache, postgres, rabbitmq
- 2,581 log lines, 83 metric series, 5 changes, 3 past incidents

| time (UTC) | kind | service | ref | note |
|---|---|---|---|---|
| 14:02 | deploy | order-router | order-router-00601 | dependency bump |
| 14:10 | config | redis-cache | cfg-redis-maxmemory | maxmemory 4gb -> 1gb, policy allkeys-lru |
| 14:40 | deploy | postgres | postgres-00846 | minor copy change |
| 14:54 | deploy | orchestrator | orchestrator-00798 | minor copy change |
| 15:04 | deploy | portfolio-consumer | portfolio-consumer-00820 | dependency bump |

## Answer key (spoiler, from `truth.json`; only `tests/eval/` reads it)

**F1 (primary)**: `redis-cache` / `idempotency_keys_evicted_by_config`, onset 14:10 UTC.

A redis-cache maxmemory configuration change evicted idempotency keys, so retried webhooks were processed as new orders and produced duplicate orders.

Decisive evidence a correct report should cite:

- redis-cache: WARN logs containing `maxmemory reached, evicting keys (allkeys-lru):`, 14:10–15:10 UTC
- order-router: WARN logs containing `idempotency key not found for retried webhook, treating as new order`, 14:11–15:10 UTC
- redis-cache: the change whose ref contains `cfg-redis-maxmemory`, 14:10–15:10 UTC

## The trap

duplicate orders look like an order-router bug after a recent deploy; the cause is a config change that evicted idempotency keys

## Run it

```powershell
# offline, no tokens: replays the recorded run
$env:LLM_BACKEND="replay"; python -m eval.run --scenarios s19_duplicate_orders --no-judge
# live (uses your Claude Code login)
$env:LLM_BACKEND="claude_code"; python -m eval.run --scenarios s19_duplicate_orders --no-judge
```
