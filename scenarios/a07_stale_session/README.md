# a07_stale_session

World: v2 app world (message-level simulation of a WhatsApp banking stack). Expected outcome: **ANSWER**.

## The ticket (all the agents are told)

> Users say the portfolio value the bot quotes does not match the app; a few say it looks like yesterday's number. Since about 10:40 UTC. Latency actually looks better than usual.

Reported 2026-10-23 11:10 UTC.

## What the data holds (`data.json`)

- Window: 2026-10-23 10:00 to 11:30 UTC (90 min)
- Services (9): wa-webhook, worker, redis-session, llm-gateway, rds-postgres, broker-api, aa-api, sender, whatsapp-api
- 3,122 log lines, 34 metric series, 3 changes, 3 past incidents
- 1,809 WhatsApp conversations traced end to end, 3 git commits with diffs

| time (UTC) | kind | service | ref | note |
|---|---|---|---|---|
| 10:38 | deploy | worker | 3d293d3 | perf: keep portfolio snapshots for a day to cut RDS load |
| 10:55 | deploy | wa-webhook | 2e0b002 | webhook: log the message type on enqueue |
| 11:13 | deploy | worker | cb4d4fb | docs: describe the session cache |

## Answer key (spoiler, from `truth.json`; only `tests/eval/` reads it)

**F1 (primary)**: `worker` / `stale_cache_config`, onset 10:38 UTC.

A commit raised session.ttl_s from 300s to 86400s, so the worker answers balance questions from portfolio snapshots cached up to a day ago instead of fetching fresh values from RDS.

Decisive evidence a correct report should cite:

- worker: the change whose ref contains `3d293d3`, 10:38–11:30 UTC
- worker: the commit touching `config/app.json`, 10:38–11:30 UTC
- worker: conversations containing `portfolio snapshot from session cache`, 10:38–11:30 UTC

## The trap

Everything looks healthier (fewer RDS queries, lower latency); there are no errors anywhere. Only the conversation context and the diff show it.

## Run it

```powershell
# live (uses your Claude Code login)
$env:LLM_BACKEND="claude_code"; python -m eval.run --scenarios a07_stale_session --no-judge
```
