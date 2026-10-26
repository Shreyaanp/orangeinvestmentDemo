# s03_config_not_deploy

World: v1 synthetic (service-level simulation). Expected outcome: **ANSWER**.

## The ticket (all the agents are told)

> Order placement is failing intermittently, and customers see timeouts when confirming trades. Started around 11:00.

Reported 2026-03-16 11:20 UTC.

## What the data holds (`data.json`)

- Window: 2026-03-16 10:00 to 12:00 UTC (120 min)
- Services (15): wa-webhook, orchestrator, llm-gateway, portfolio-svc, aa-sync, broker-gateway, order-router, market-data, auth-kyc, portfolio-consumer, msg-delivery, web-app, redis-cache, postgres, rabbitmq
- 2,906 log lines, 81 metric series, 4 changes, 3 past incidents

| time (UTC) | kind | service | ref | note |
|---|---|---|---|---|
| 10:08 | deploy | msg-delivery | msg-delivery-00401 | minor copy change |
| 10:40 | deploy | wa-webhook | wa-webhook-00246 | dependency bump |
| 11:00 | config | broker-gateway | cfg-broker-timeout-ms | BROKER_TIMEOUT_MS 3000 -> 800 |
| 11:25 | deploy | postgres | postgres-00294 | minor copy change |

## Answer key (spoiler, from `truth.json`; only `tests/eval/` reads it)

**F1 (primary)**: `broker-gateway` / `config_change_timeout`, onset 11:00 UTC.

A configuration change lowered broker-gateway's broker request timeout (3000ms to 800ms), so many broker calls abort with timeouts. No deploy was involved.

Decisive evidence a correct report should cite:

- broker-gateway: ERROR logs containing `broker request aborted: exceeded configured timeout of 800ms`, 11:00–12:00 UTC
- broker-gateway: the change whose ref contains `cfg-broker-timeout-ms`, 11:00–12:00 UTC

## The trap

deploy history is clean; the only change is a config change that must be looked up explicitly

## Run it

```powershell
# offline, no tokens: replays the recorded run
$env:LLM_BACKEND="replay"; python -m eval.run --scenarios s03_config_not_deploy --no-judge
# live (uses your Claude Code login)
$env:LLM_BACKEND="claude_code"; python -m eval.run --scenarios s03_config_not_deploy --no-judge
```
