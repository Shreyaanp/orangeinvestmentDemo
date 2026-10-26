# f04_client_contract

World: v1 synthetic (service-level simulation). Expected outcome: **ANSWER**.

## The ticket (all the agents are told)

> The portfolio page shows an error for many users since about 14:00; the assistant's balance answers still work.

Reported 2026-05-11 14:20 UTC.

## What the data holds (`data.json`)

- Window: 2026-05-11 13:00 to 15:00 UTC (120 min)
- Services (15): wa-webhook, orchestrator, llm-gateway, portfolio-svc, aa-sync, broker-gateway, order-router, market-data, auth-kyc, portfolio-consumer, msg-delivery, web-app, redis-cache, postgres, rabbitmq
- 3,397 log lines, 81 metric series, 5 changes, 3 past incidents

| time (UTC) | kind | service | ref | note |
|---|---|---|---|---|
| 13:21 | deploy | postgres | postgres-00682 | log level tweak |
| 13:47 | deploy | portfolio-svc | portfolio-svc-00733 | upgrade json serialization library |
| 13:59 | deploy | web-app | web-app-00512 | portfolio page v5.2: new account switcher |
| 14:46 | deploy | order-router | order-router-00477 | log level tweak |
| 14:50 | deploy | portfolio-consumer | portfolio-consumer-00496 | log level tweak |

## Answer key (spoiler, from `truth.json`; only `tests/eval/` reads it)

**F1 (primary)**: `web-app` / `bad_deploy_client_contract`, onset 14:00 UTC.

A web-app release (new account switcher) sends portfolio requests without the required account_id, so portfolio-svc rejects them with 400 and the page errors.

Decisive evidence a correct report should cite:

- portfolio-svc: WARN logs containing `rejected request from web-app/5.2.0: 400 missing required parameter 'account_id'`, 14:00–15:00 UTC
- web-app: the change whose ref contains `web-app-00512`, 13:59–15:00 UTC

## The trap

the errors are logged by the callee (portfolio-svc, which also deployed recently) but the cause is the caller's release

## Run it

```powershell
# live (uses your Claude Code login)
$env:LLM_BACKEND="claude_code"; python -m eval.run --scenarios f04_client_contract --no-judge
```
