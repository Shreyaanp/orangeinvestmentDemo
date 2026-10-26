# s17_retry_storm

World: v1 synthetic (service-level simulation). Expected outcome: **ANSWER**.

## The ticket (all the agents are told)

> Order placement is failing for many customers and the broker integration looks overloaded. Started around 14:00.

Reported 2026-04-03 14:25 UTC.

## What the data holds (`data.json`)

- Window: 2026-04-03 13:00 to 15:00 UTC (120 min)
- Services (15): wa-webhook, orchestrator, llm-gateway, portfolio-svc, aa-sync, broker-gateway, order-router, market-data, auth-kyc, portfolio-consumer, msg-delivery, web-app, redis-cache, postgres, rabbitmq
- 4,394 log lines, 81 metric series, 3 changes, 3 past incidents

| time (UTC) | kind | service | ref | note |
|---|---|---|---|---|
| 13:23 | deploy | portfolio-consumer | portfolio-consumer-00524 | log level tweak |
| 13:39 | deploy | portfolio-consumer | portfolio-consumer-00991 | dependency bump |
| 14:48 | deploy | web-app | web-app-00886 | minor copy change |

## Answer key (spoiler, from `truth.json`; only `tests/eval/` reads it)

**F1 (primary)**: `order-router` / `retry_storm_no_backoff`, onset 14:00 UTC.

order-router retries failed broker calls immediately without backoff (a retry storm), overloading broker-gateway after a brief broker blip that had already recovered.

Decisive evidence a correct report should cite:

- order-router: WARN logs containing `retrying place_order immediately (attempt 5) without backoff`, 14:00–15:00 UTC

## The trap

a short broker blip triggered the storm but already recovered; the sustained overload comes from missing retry backoff

## Run it

```powershell
# offline, no tokens: replays the recorded run
$env:LLM_BACKEND="replay"; python -m eval.run --scenarios s17_retry_storm --no-judge
# live (uses your Claude Code login)
$env:LLM_BACKEND="claude_code"; python -m eval.run --scenarios s17_retry_storm --no-judge
```
