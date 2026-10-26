# f06_mq_insufficient

World: v1 synthetic (service-level simulation). Expected outcome: **INCONCLUSIVE**.

## The ticket (all the agents are told)

> Portfolio updates after bank-account syncs are delayed for many users since about 11:00.

Reported 2026-05-15 11:30 UTC.

## What the data holds (`data.json`)

- Window: 2026-05-15 10:00 to 12:00 UTC (120 min)
- Services (15): wa-webhook, orchestrator, llm-gateway, portfolio-svc, aa-sync, broker-gateway, order-router, market-data, auth-kyc, portfolio-consumer, msg-delivery, web-app, redis-cache, postgres, rabbitmq
- 2,140 log lines, 81 metric series, 4 changes, 3 past incidents

| time (UTC) | kind | service | ref | note |
|---|---|---|---|---|
| 10:12 | deploy | msg-delivery | msg-delivery-00446 | minor copy change |
| 10:26 | deploy | portfolio-consumer | portfolio-consumer-00629 | dependency bump |
| 10:57 | deploy | aa-sync | aa-sync-00648 | refactor consent refresh scheduler |
| 11:26 | deploy | wa-webhook | wa-webhook-00501 | log level tweak |

## Answer key (spoiler, from `truth.json`; only `tests/eval/` reads it)

**F1 (primary)**: `rabbitmq` / `memory_alarm_flow_control`, onset 11:00 UTC.

A rabbitmq memory alarm blocked publishers (flow control), so aa-sync could publish few portfolio updates. The broker's own logs and memory metric are deliberately missing from the data.

Decisive evidence a correct report should cite:

- rabbitmq: WARN logs containing `memory resource limit alarm set, blocking publishing connections`, 11:00–12:00 UTC

## The trap

the broker's logs and memory metric are missing; a producer deploy and a slow database are both plausible but unproven

## Run it

```powershell
# live (uses your Claude Code login)
$env:LLM_BACKEND="claude_code"; python -m eval.run --scenarios f06_mq_insufficient --no-judge
```
