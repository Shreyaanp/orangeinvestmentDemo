# s07_logs_vs_metrics

World: v1 synthetic (service-level simulation). Expected outcome: **ANSWER**.

## The ticket (all the agents are told)

> Users say the assistant quotes stock prices that have not moved in about ten minutes while the market is open.

Reported 2026-03-20 10:45 UTC.

## What the data holds (`data.json`)

- Window: 2026-03-20 09:30 to 11:30 UTC (120 min)
- Services (15): wa-webhook, orchestrator, llm-gateway, portfolio-svc, aa-sync, broker-gateway, order-router, market-data, auth-kyc, portfolio-consumer, msg-delivery, web-app, redis-cache, postgres, rabbitmq
- 2,201 log lines, 81 metric series, 3 changes, 3 past incidents

| time (UTC) | kind | service | ref | note |
|---|---|---|---|---|
| 09:52 | deploy | broker-gateway | broker-gateway-00518 | metrics label rename |
| 11:05 | deploy | wa-webhook | wa-webhook-00683 | dependency bump |
| 11:20 | deploy | orchestrator | orchestrator-00702 | minor copy change |

## Answer key (spoiler, from `truth.json`; only `tests/eval/` reads it)

**F1 (primary)**: `market-data` / `upstream_feed_stalled`, onset 10:25 UTC.

The upstream market-data vendor feed stalled, so prices stopped updating (price age grew to about ten minutes) while the service kept logging heartbeat OK.

Decisive evidence a correct report should cite:

- market-data: metric `price_age_s` at or above 480.0, 10:25–11:30 UTC

## The trap

service logs keep reporting 'feed heartbeat ok' while the price-age metric shows the feed is stale

## Run it

```powershell
# offline, no tokens: replays the recorded run
$env:LLM_BACKEND="replay"; python -m eval.run --scenarios s07_logs_vs_metrics --no-judge
# live (uses your Claude Code login)
$env:LLM_BACKEND="claude_code"; python -m eval.run --scenarios s07_logs_vs_metrics --no-judge
```
