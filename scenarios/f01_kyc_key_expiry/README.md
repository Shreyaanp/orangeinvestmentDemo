# f01_kyc_key_expiry

World: v1 synthetic (service-level simulation). Expected outcome: **ANSWER**.

## The ticket (all the agents are told)

> New users cannot finish KYC verification and some returning users are stuck at login checks since about 11:50.

Reported 2026-05-04 12:20 UTC.

## What the data holds (`data.json`)

- Window: 2026-05-04 11:00 to 13:00 UTC (120 min)
- Services (15): wa-webhook, orchestrator, llm-gateway, portfolio-svc, aa-sync, broker-gateway, order-router, market-data, auth-kyc, portfolio-consumer, msg-delivery, web-app, redis-cache, postgres, rabbitmq
- 3,272 log lines, 81 metric series, 4 changes, 3 past incidents

| time (UTC) | kind | service | ref | note |
|---|---|---|---|---|
| 11:12 | deploy | msg-delivery | msg-delivery-00286 | log level tweak |
| 11:14 | deploy | orchestrator | orchestrator-00921 | metrics label rename |
| 11:48 | flag | web-app | flag-onboarding-v2 | onboarding_v2 rollout 10% -> 50% |
| 12:49 | deploy | portfolio-consumer | portfolio-consumer-00725 | dependency bump |

## Answer key (spoiler, from `truth.json`; only `tests/eval/` reads it)

**F1 (primary)**: `auth-kyc` / `credential_expiry`, onset 11:50 UTC.

auth-kyc's API key for the external KYC vendor expired, so every vendor call is rejected with 401 and KYC checks fail. Nothing was deployed or reconfigured.

Decisive evidence a correct report should cite:

- auth-kyc: ERROR logs containing `kyc vendor rejected request: 401 unauthorized, api key kyc-prod-2025 expired`, 11:50–13:00 UTC

## The trap

no change explains the fault (a credential expired); a flag rollout of a new onboarding flow lands two minutes earlier

## Run it

```powershell
# live (uses your Claude Code login)
$env:LLM_BACKEND="claude_code"; python -m eval.run --scenarios f01_kyc_key_expiry --no-judge
```
