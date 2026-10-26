# a06_whatsapp_throttle

World: v2 app world (message-level simulation of a WhatsApp banking stack). Expected outcome: **ANSWER**.

## The ticket (all the agents are told)

> Many users say the bot never replied, or replied very late, since about 09:45 UTC. The worker dashboards look normal.

Reported 2026-10-23 10:12 UTC.

## What the data holds (`data.json`)

- Window: 2026-10-23 09:00 to 10:30 UTC (90 min)
- Services (9): wa-webhook, worker, redis-session, llm-gateway, rds-postgres, broker-api, aa-api, sender, whatsapp-api
- 5,355 log lines, 34 metric series, 4 changes, 3 past incidents
- 1,800 WhatsApp conversations traced end to end, 4 git commits with diffs

| time (UTC) | kind | service | ref | note |
|---|---|---|---|---|
| 09:10 | deploy | wa-webhook | f714a2a | webhook: log the message type on enqueue |
| 09:25 | deploy | worker | 78d2a15 | docs: describe the session cache |
| 09:42 | deploy | worker | 8df445e | feat: greet first-time users by name |
| 10:06 | deploy | sender | c3942e4 | sender: send an explicit content-type header |

## Answer key (spoiler, from `truth.json`; only `tests/eval/` reads it)

**F1 (primary)**: `whatsapp-api` / `external_rate_limit`, onset 09:45 UTC.

The WhatsApp Cloud API began rejecting sends with 429 / error 130429 (throughput limit, about 12 messages a minute); the sender retries with backoff, so replies are late and some are given up on.

Decisive evidence a correct report should cite:

- sender: WARN logs containing `130429`, 09:45–10:30 UTC
- sender: metric `err_rate` at or above 0.2, 09:45–10:30 UTC

## The trap

A worker prompt deploy lands three minutes before; worker, LLM and tool telemetry are all normal. The fault is downstream of our code.

## Run it

```powershell
# live (uses your Claude Code login)
$env:LLM_BACKEND="claude_code"; python -m eval.run --scenarios a06_whatsapp_throttle --no-judge
```
