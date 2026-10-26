# f05_prompt_config

World: v1 synthetic (service-level simulation). Expected outcome: **ANSWER**.

## The ticket (all the agents are told)

> Many assistant conversations end with 'Sorry, something went wrong' since about 16:00. The LLM provider status page is green.

Reported 2026-05-13 16:25 UTC.

## What the data holds (`data.json`)

- Window: 2026-05-13 15:00 to 17:00 UTC (120 min)
- Services (15): wa-webhook, orchestrator, llm-gateway, portfolio-svc, aa-sync, broker-gateway, order-router, market-data, auth-kyc, portfolio-consumer, msg-delivery, web-app, redis-cache, postgres, rabbitmq
- 2,742 log lines, 81 metric series, 5 changes, 3 past incidents
- 1 injected tool failures (the tools themselves flake)

| time (UTC) | kind | service | ref | note |
|---|---|---|---|---|
| 15:13 | deploy | portfolio-svc | portfolio-svc-00267 | minor copy change |
| 15:22 | deploy | portfolio-consumer | portfolio-consumer-00195 | dependency bump |
| 15:38 | deploy | msg-delivery | msg-delivery-00172 | metrics label rename |
| 15:56 | deploy | llm-gateway | llm-gateway-00388 | bump http client to 2.31 |
| 16:00 | config | orchestrator | cfg-planner-prompt | PLANNER_PROMPT_VERSION v41 -> v42 |

## Answer key (spoiler, from `truth.json`; only `tests/eval/` reads it)

**F1 (primary)**: `orchestrator` / `prompt_config_change`, onset 16:00 UTC.

A configuration change switched the orchestrator's planner prompt to version v42, whose output is prose instead of the expected JSON tool plan, so plans fail to parse and conversations abort.

Decisive evidence a correct report should cite:

- orchestrator: ERROR logs containing `could not parse tool plan from model output (planner prompt v42): expected JSON object, got prose`, 16:00–17:00 UTC
- orchestrator: the change whose ref contains `cfg-planner-prompt`, 16:00–17:00 UTC

## The trap

the change is a config change (not a deploy) and the first change lookup times out; the failure metric sits on llm-gateway, which deployed four minutes earlier

## Run it

```powershell
# live (uses your Claude Code login)
$env:LLM_BACKEND="claude_code"; python -m eval.run --scenarios f05_prompt_config --no-judge
```
