# s06_clock_skew

World: v1 synthetic (service-level simulation). Expected outcome: **ANSWER**.

## The ticket (all the agents are told)

> Order placement and portfolio sync are failing intermittently since about 12:00, and the assistant is slow to reply.

Reported 2026-03-19 12:25 UTC.

## What the data holds (`data.json`)

- Window: 2026-03-19 11:00 to 13:00 UTC (120 min)
- Services (15): wa-webhook, orchestrator, llm-gateway, portfolio-svc, aa-sync, broker-gateway, order-router, market-data, auth-kyc, portfolio-consumer, msg-delivery, web-app, redis-cache, postgres, rabbitmq
- 3,103 log lines, 81 metric series, 3 changes, 3 past incidents

| time (UTC) | kind | service | ref | note |
|---|---|---|---|---|
| 11:05 | deploy | wa-webhook | wa-webhook-00904 | dependency bump |
| 11:16 | deploy | web-app | web-app-00369 | minor copy change |
| 12:31 | deploy | llm-gateway | llm-gateway-00188 | log level tweak |

## Answer key (spoiler, from `truth.json`; only `tests/eval/` reads it)

**F1 (primary)**: `broker-gateway` / `upstream_rate_limit`, onset 12:00 UTC.

The external broker API rate-limited broker-gateway (HTTP 429), so broker calls failed. The orchestrator host's skewed clock made its errors look like they came first.

Decisive evidence a correct report should cite:

- broker-gateway: ERROR logs containing `broker api returned 429 too many requests, retry-after 30s`, 12:00–13:00 UTC

## The trap

orchestrator host clock is 5 minutes behind, so its errors appear to precede the real cause

## Run it

```powershell
# offline, no tokens: replays the recorded run
$env:LLM_BACKEND="replay"; python -m eval.run --scenarios s06_clock_skew --no-judge
# live (uses your Claude Code login)
$env:LLM_BACKEND="claude_code"; python -m eval.run --scenarios s06_clock_skew --no-judge
```
