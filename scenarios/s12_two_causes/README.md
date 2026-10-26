# s12_two_causes

World: v1 synthetic (service-level simulation). Expected outcome: **ANSWER**.

## The ticket (all the agents are told)

> The assistant is slow, the token-cost alert fired, and some users received blank notifications.

Reported 2026-03-27 11:40 UTC.

## What the data holds (`data.json`)

- Window: 2026-03-27 10:00 to 12:00 UTC (120 min)
- Services (15): wa-webhook, orchestrator, llm-gateway, portfolio-svc, aa-sync, broker-gateway, order-router, market-data, auth-kyc, portfolio-consumer, msg-delivery, web-app, redis-cache, postgres, rabbitmq
- 2,878 log lines, 81 metric series, 4 changes, 3 past incidents

| time (UTC) | kind | service | ref | note |
|---|---|---|---|---|
| 10:16 | deploy | redis-cache | redis-cache-00299 | log level tweak |
| 10:33 | deploy | orchestrator | orchestrator-00508 | log level tweak |
| 11:24 | deploy | msg-delivery | msg-delivery-00290 | notification template refactor |
| 11:46 | deploy | postgres | postgres-00613 | metrics label rename |

## Answer key (spoiler, from `truth.json`; only `tests/eval/` reads it)

**F1 (primary)**: `orchestrator` / `runaway_agent_loop`, onset 10:55 UTC.

A runaway agent loop in the orchestrator repeated tool calls (for example 38 identical get_holdings calls in one session), spiking llm-gateway token use and latency.

Decisive evidence a correct report should cite:

- orchestrator: ERROR logs containing `agent loop detected: repeated tool call get_holdings x38 in one session, aborting`, 10:55–12:00 UTC
- llm-gateway: metric `tokens_per_min` at or above 320000.0, 10:55–12:00 UTC

**F2 (secondary)**: `msg-delivery` / `notification_template_bug`, onset 11:25 UTC.

A msg-delivery release (notification template refactor) fails to render notifications (missing variable portfolio_value), producing blank notifications.

Decisive evidence a correct report should cite:

- msg-delivery: ERROR logs containing `template render failed: missing variable 'portfolio_value'`, 11:25–12:00 UTC
- msg-delivery: WARN logs containing `notification sent with empty body after template render failure`, 11:26–12:00 UTC
- msg-delivery: the change whose ref contains `msg-delivery-00290`, 11:24–12:00 UTC

## The trap

two unrelated concurrent faults; both must be found, the primary ranked first

## Run it

```powershell
# offline, no tokens: replays the recorded run
$env:LLM_BACKEND="replay"; python -m eval.run --scenarios s12_two_causes --no-judge
# live (uses your Claude Code login)
$env:LLM_BACKEND="claude_code"; python -m eval.run --scenarios s12_two_causes --no-judge
```
