# f02_delivery_memory_leak

World: v1 synthetic (service-level simulation). Expected outcome: **ANSWER**.

## The ticket (all the agents are told)

> WhatsApp replies and portfolio notifications are arriving late, and some not at all, for the last half hour.

Reported 2026-05-06 09:40 UTC.

## What the data holds (`data.json`)

- Window: 2026-05-06 08:00 to 10:00 UTC (120 min)
- Services (15): wa-webhook, orchestrator, llm-gateway, portfolio-svc, aa-sync, broker-gateway, order-router, market-data, auth-kyc, portfolio-consumer, msg-delivery, web-app, redis-cache, postgres, rabbitmq
- 2,450 log lines, 81 metric series, 4 changes, 3 past incidents

| time (UTC) | kind | service | ref | note |
|---|---|---|---|---|
| 08:48 | deploy | wa-webhook | wa-webhook-00978 | minor copy change |
| 09:08 | deploy | orchestrator | orchestrator-01207 | tune session resume timeout |
| 09:29 | deploy | wa-webhook | wa-webhook-00167 | metrics label rename |
| 09:49 | deploy | msg-delivery | msg-delivery-00594 | log level tweak |

## Answer key (spoiler, from `truth.json`; only `tests/eval/` reads it)

**F1 (primary)**: `msg-delivery` / `memory_leak`, onset 08:15 UTC.

msg-delivery leaks memory: heap grows steadily until containers are OOM-killed and restart, so outbound messages back up and deliveries are late or lost.

Decisive evidence a correct report should cite:

- msg-delivery: WARN logs containing `heap usage`, 08:15–10:00 UTC
- msg-delivery: ERROR logs containing `container OOMKilled (memory limit 512Mi), restarting`, 09:10–10:00 UTC

## The trap

the leak starts long before the symptoms (no sharp onset, no change); an orchestrator deploy lands just as users notice

## Run it

```powershell
# live (uses your Claude Code login)
$env:LLM_BACKEND="claude_code"; python -m eval.run --scenarios f02_delivery_memory_leak --no-judge
```
