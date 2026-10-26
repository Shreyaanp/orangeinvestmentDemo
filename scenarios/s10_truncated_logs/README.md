# s10_truncated_logs

World: v1 synthetic (service-level simulation). Expected outcome: **ANSWER**.

## The ticket (all the agents are told)

> New customers cannot complete signup and KYC since about 09:55.

Reported 2026-03-25 10:20 UTC.

## What the data holds (`data.json`)

- Window: 2026-03-25 09:00 to 11:00 UTC (120 min)
- Services (15): wa-webhook, orchestrator, llm-gateway, portfolio-svc, aa-sync, broker-gateway, order-router, market-data, auth-kyc, portfolio-consumer, msg-delivery, web-app, redis-cache, postgres, rabbitmq
- 2,621 log lines, 81 metric series, 3 changes, 3 past incidents
- 1 injected tool failures (the tools themselves flake)

| time (UTC) | kind | service | ref | note |
|---|---|---|---|---|
| 09:13 | deploy | postgres | postgres-00185 | metrics label rename |
| 10:48 | deploy | auth-kyc | auth-kyc-00489 | log level tweak |
| 10:54 | deploy | market-data | market-data-00509 | minor copy change |

## Answer key (spoiler, from `truth.json`; only `tests/eval/` reads it)

**F1 (primary)**: `auth-kyc` / `vendor_outage`, onset 09:55 UTC.

The external KYC vendor used by auth-kyc was down (connection refused), so KYC and signup checks failed.

Decisive evidence a correct report should cite:

- auth-kyc: ERROR logs containing `kyc vendor connection refused: tcp connect to kyc-provider failed`, 09:55–11:00 UTC

## The trap

the log tool caps results at 50, so the decisive lines only appear after narrowing the query

## Run it

```powershell
# offline, no tokens: replays the recorded run
$env:LLM_BACKEND="replay"; python -m eval.run --scenarios s10_truncated_logs --no-judge
# live (uses your Claude Code login)
$env:LLM_BACKEND="claude_code"; python -m eval.run --scenarios s10_truncated_logs --no-judge
```
