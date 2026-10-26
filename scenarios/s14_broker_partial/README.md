# s14_broker_partial

World: v1 synthetic (service-level simulation). Expected outcome: **ANSWER**.

## The ticket (all the agents are told)

> Customers see 'order pending' for minutes after placing an order, and some retry. Started around 10:00.

Reported 2026-03-31 10:25 UTC.

## What the data holds (`data.json`)

- Window: 2026-03-31 09:00 to 11:00 UTC (120 min)
- Services (15): wa-webhook, orchestrator, llm-gateway, portfolio-svc, aa-sync, broker-gateway, order-router, market-data, auth-kyc, portfolio-consumer, msg-delivery, web-app, redis-cache, postgres, rabbitmq
- 2,932 log lines, 81 metric series, 4 changes, 3 past incidents

| time (UTC) | kind | service | ref | note |
|---|---|---|---|---|
| 09:18 | deploy | orchestrator | orchestrator-00669 | minor copy change |
| 09:24 | deploy | orchestrator | orchestrator-00952 | metrics label rename |
| 09:25 | deploy | wa-webhook | wa-webhook-00939 | minor copy change |
| 09:50 | deploy | order-router | order-router-00455 | log level tweak |

## Answer key (spoiler, from `truth.json`; only `tests/eval/` reads it)

**F1 (primary)**: `broker-gateway` / `order_status_endpoint_degraded`, onset 10:00 UTC.

broker-gateway's order-status endpoint was degraded (slow), so order confirmations arrive late; order-router errors and retries are a consequence.

Decisive evidence a correct report should cite:

- broker-gateway: WARN logs containing `order status endpoint slow: GET /orders/status took`, 10:00–11:00 UTC

## The trap

errors surface in order-router (an effect), while the degraded dependency is broker-gateway

## Run it

```powershell
# offline, no tokens: replays the recorded run
$env:LLM_BACKEND="replay"; python -m eval.run --scenarios s14_broker_partial --no-judge
# live (uses your Claude Code login)
$env:LLM_BACKEND="claude_code"; python -m eval.run --scenarios s14_broker_partial --no-judge
```
