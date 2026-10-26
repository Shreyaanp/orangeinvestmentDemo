# s08_stale_history

World: v1 synthetic (service-level simulation). Expected outcome: **ANSWER**.

## The ticket (all the agents are told)

> Assistant replies are very slow and some time out since about 14:00, and users report late notifications.

Reported 2026-03-23 14:20 UTC.

## What the data holds (`data.json`)

- Window: 2026-03-23 13:00 to 15:00 UTC (120 min)
- Services (15): wa-webhook, orchestrator, llm-gateway, portfolio-svc, aa-sync, broker-gateway, order-router, market-data, auth-kyc, portfolio-consumer, msg-delivery, web-app, redis-cache, postgres, rabbitmq
- 3,107 log lines, 81 metric series, 3 changes, 4 past incidents

| time (UTC) | kind | service | ref | note |
|---|---|---|---|---|
| 13:24 | deploy | order-router | order-router-00311 | minor copy change |
| 13:26 | deploy | auth-kyc | auth-kyc-00534 | minor copy change |
| 14:52 | deploy | aa-sync | aa-sync-00224 | minor copy change |

## Answer key (spoiler, from `truth.json`; only `tests/eval/` reads it)

**F1 (primary)**: `llm-gateway` / `provider_rate_limit`, onset 13:55 UTC.

The LLM provider rate-limited llm-gateway (HTTP 429), causing retries, fallbacks and slow or failing assistant replies.

Decisive evidence a correct report should cite:

- llm-gateway: ERROR logs containing `provider returned 429 rate limited, retrying with backoff`, 13:55–15:00 UTC

## The trap

a past incident with near-identical symptoms had a different cause; redis hit ratio dips slightly as a bystander

## Run it

```powershell
# offline, no tokens: replays the recorded run
$env:LLM_BACKEND="replay"; python -m eval.run --scenarios s08_stale_history --no-judge
# live (uses your Claude Code login)
$env:LLM_BACKEND="claude_code"; python -m eval.run --scenarios s08_stale_history --no-judge
```
