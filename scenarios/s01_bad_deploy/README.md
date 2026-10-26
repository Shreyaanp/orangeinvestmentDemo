# s01_bad_deploy

World: v1 synthetic (service-level simulation). Expected outcome: **ANSWER**.

## The ticket (all the agents are told)

> Customers report that placing orders fails with an error since around 13:10. Support has 40+ tickets.

Reported 2026-03-12 13:35 UTC.

## What the data holds (`data.json`)

- Window: 2026-03-12 12:00 to 14:00 UTC (120 min)
- Services (15): wa-webhook, orchestrator, llm-gateway, portfolio-svc, aa-sync, broker-gateway, order-router, market-data, auth-kyc, portfolio-consumer, msg-delivery, web-app, redis-cache, postgres, rabbitmq
- 2,695 log lines, 81 metric series, 4 changes, 3 past incidents

| time (UTC) | kind | service | ref | note |
|---|---|---|---|---|
| 12:32 | deploy | auth-kyc | auth-kyc-00714 | metrics label rename |
| 12:39 | deploy | msg-delivery | msg-delivery-00248 | dependency bump |
| 12:47 | deploy | llm-gateway | llm-gateway-00247 | log level tweak |
| 13:09 | deploy | order-router | order-router-00418 | refactor order validation |

## Answer key (spoiler, from `truth.json`; only `tests/eval/` reads it)

**F1 (primary)**: `order-router` / `bad_deploy`, onset 13:10 UTC.

order-router release order-router-00418 introduced a bug in order validation (an unhandled KeyError on limit_price), so order placement fails with exceptions.

Decisive evidence a correct report should cite:

- order-router: ERROR logs containing `unhandled exception in place_order: KeyError 'limit_price'`, 13:10–14:00 UTC
- order-router: the change whose ref contains `order-router-00418`, 13:09–14:00 UTC

## The trap

none (control case)

## Run it

```powershell
# offline, no tokens: replays the recorded run
$env:LLM_BACKEND="replay"; python -m eval.run --scenarios s01_bad_deploy --no-judge
# live (uses your Claude Code login)
$env:LLM_BACKEND="claude_code"; python -m eval.run --scenarios s01_bad_deploy --no-judge
```
