# s15_rebalance_storm

World: v1 synthetic (service-level simulation). Expected outcome: **ANSWER**.

## The ticket (all the agents are told)

> WhatsApp replies are arriving late for many users, and some never arrive. Started around 09:00.

Reported 2026-04-01 09:35 UTC.

## What the data holds (`data.json`)

- Window: 2026-04-01 08:00 to 10:00 UTC (120 min)
- Services (15): wa-webhook, orchestrator, llm-gateway, portfolio-svc, aa-sync, broker-gateway, order-router, market-data, auth-kyc, portfolio-consumer, msg-delivery, web-app, redis-cache, postgres, rabbitmq
- 2,620 log lines, 81 metric series, 4 changes, 3 past incidents

| time (UTC) | kind | service | ref | note |
|---|---|---|---|---|
| 08:25 | deploy | orchestrator | orchestrator-00797 | metrics label rename |
| 08:49 | deploy | msg-delivery | msg-delivery-00277 | batch size increase for delivery receipts |
| 09:34 | deploy | aa-sync | aa-sync-00950 | minor copy change |
| 09:48 | deploy | web-app | web-app-00344 | minor copy change |

## Answer key (spoiler, from `truth.json`; only `tests/eval/` reads it)

**F1 (primary)**: `msg-delivery` / `memory_leak_oom_crash_loop`, onset 08:50 UTC.

A msg-delivery release leaks memory, causing out-of-memory kills, a consumer crash loop and queue rebalancing, so outbound messages lag.

Decisive evidence a correct report should cite:

- msg-delivery: WARN logs containing `memory usage`, 08:50–10:00 UTC
- msg-delivery: ERROR logs containing `worker killed: out of memory, restarting consumer`, 09:05–10:00 UTC
- msg-delivery: the change whose ref contains `msg-delivery-00277`, 08:49–10:00 UTC

## The trap

queue lag looks like a producer burst; the real cause is a consumer crash loop after a leaky release

## Run it

```powershell
# offline, no tokens: replays the recorded run
$env:LLM_BACKEND="replay"; python -m eval.run --scenarios s15_rebalance_storm --no-judge
# live (uses your Claude Code login)
$env:LLM_BACKEND="claude_code"; python -m eval.run --scenarios s15_rebalance_storm --no-judge
```
