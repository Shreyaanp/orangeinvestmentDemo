# s16_schema_dlq

World: v1 synthetic (service-level simulation). Expected outcome: **ANSWER**.

## The ticket (all the agents are told)

> Portfolio updates are not arriving for about half of users since 11:20. Ops sees the dead-letter queue growing.

Reported 2026-04-02 11:50 UTC.

## What the data holds (`data.json`)

- Window: 2026-04-02 10:20 to 12:20 UTC (120 min)
- Services (15): wa-webhook, orchestrator, llm-gateway, portfolio-svc, aa-sync, broker-gateway, order-router, market-data, auth-kyc, portfolio-consumer, msg-delivery, web-app, redis-cache, postgres, rabbitmq
- 2,775 log lines, 81 metric series, 5 changes, 3 past incidents

| time (UTC) | kind | service | ref | note |
|---|---|---|---|---|
| 10:27 | deploy | wa-webhook | wa-webhook-00329 | metrics label rename |
| 10:50 | deploy | portfolio-consumer | portfolio-consumer-00091 | log level tweak |
| 10:58 | deploy | order-router | order-router-00991 | metrics label rename |
| 11:19 | deploy | aa-sync | aa-sync-00633 | normalize holdings payload v2 |
| 12:11 | deploy | portfolio-consumer | portfolio-consumer-00929 | metrics label rename |

## Answer key (spoiler, from `truth.json`; only `tests/eval/` reads it)

**F1 (primary)**: `aa-sync` / `message_schema_change`, onset 11:20 UTC.

An aa-sync release changed the message schema (a renamed field), so portfolio-consumer validation fails and messages pile up in the dead-letter queue.

Decisive evidence a correct report should cite:

- portfolio-consumer: ERROR logs containing `schema validation failed: unexpected field 'positions' (expected 'holdings')`, 11:20–12:20 UTC
- aa-sync: the change whose ref contains `aa-sync-00633`, 11:19–12:20 UTC

## The trap

errors appear in the consumer, but the deploy that changed the schema was on the producer

## Run it

```powershell
# offline, no tokens: replays the recorded run
$env:LLM_BACKEND="replay"; python -m eval.run --scenarios s16_schema_dlq --no-judge
# live (uses your Claude Code login)
$env:LLM_BACKEND="claude_code"; python -m eval.run --scenarios s16_schema_dlq --no-judge
```
