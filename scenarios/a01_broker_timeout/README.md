# a01_broker_timeout

World: v2 app world (message-level simulation of a WhatsApp banking stack). Expected outcome: **ANSWER**.

## The ticket (all the agents are told)

> Support tickets since about 09:40 UTC: users asking about order status on WhatsApp keep getting 'Sorry, I couldn't fetch that right now'. Balance questions seem fine.

Reported 2026-10-20 10:02 UTC.

## What the data holds (`data.json`)

- Window: 2026-10-20 09:00 to 10:30 UTC (90 min)
- Services (9): wa-webhook, worker, redis-session, llm-gateway, rds-postgres, broker-api, aa-api, sender, whatsapp-api
- 3,169 log lines, 34 metric series, 4 changes, 3 past incidents
- 1,769 WhatsApp conversations traced end to end, 4 git commits with diffs

| time (UTC) | kind | service | ref | note |
|---|---|---|---|---|
| 09:14 | deploy | wa-webhook | 3e445ed | webhook: log the message type on enqueue |
| 09:33 | deploy | sender | 50cc57e | chore: bump httpx to 0.27.2 |
| 09:38 | deploy | worker | 6e7b46e | perf: tighten broker tool timeout for faster replies |
| 10:07 | deploy | sender | 44aee6e | sender: send an explicit content-type header |

## Answer key (spoiler, from `truth.json`; only `tests/eval/` reads it)

**F1 (primary)**: `worker` / `bad_config_commit`, onset 09:38 UTC.

A commit lowered the broker tool timeout in config/app.json from 5s to 0.5s; the partner broker API's normal latency (~450ms median) now exceeds it for a large share of calls, so order-status questions get the apology reply.

Decisive evidence a correct report should cite:

- worker: the change whose ref contains `6e7b46e`, 09:38–10:30 UTC
- worker: WARN logs containing `tool broker failed`, 09:38–10:30 UTC
- worker: the commit touching `config/app.json`, 09:38–10:30 UTC

## The trap

The broker API itself is healthy (latency unchanged); a sender deploy lands just before. The fault is our own timeout config, visible only in the diff.

## Run it

```powershell
# live (uses your Claude Code login)
$env:LLM_BACKEND="claude_code"; python -m eval.run --scenarios a01_broker_timeout --no-judge
```
