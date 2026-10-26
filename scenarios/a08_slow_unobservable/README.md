# a08_slow_unobservable

World: v2 app world (message-level simulation of a WhatsApp banking stack). Expected outcome: **INCONCLUSIVE**.

## The ticket (all the agents are told)

> Replies feel slow since about 09:40 UTC (users say 'the bot takes ages'). No errors reported.

Reported 2026-10-24 10:10 UTC.

## What the data holds (`data.json`)

- Window: 2026-10-24 09:00 to 10:30 UTC (90 min)
- Services (9): wa-webhook, worker, redis-session, llm-gateway, rds-postgres, broker-api, aa-api, sender, whatsapp-api
- 2,236 log lines, 34 metric series, 4 changes, 3 past incidents
- 1,771 WhatsApp conversations traced end to end, 4 git commits with diffs

| time (UTC) | kind | service | ref | note |
|---|---|---|---|---|
| 09:09 | deploy | worker | d683552 | prompt: friendlier tone |
| 09:24 | deploy | wa-webhook | f34e6ff | webhook: log the message type on enqueue |
| 09:39 | deploy | worker | 289715e | feat: include the last 20 turns of history in the prompt |
| 10:04 | deploy | sender | 5915e9c | sender: send an explicit content-type header |

## Answer key (spoiler, from `truth.json`; only `tests/eval/` reads it)

**F1 (primary)**: `llm-gateway` / `provider_latency`, onset 09:40 UTC.

The LLM provider became about 3x slower; with the gateway's telemetry export broken and worker traces off, it cannot be told apart from the prompt-history deploy a minute earlier.

Decisive evidence a correct report should cite:

- llm-gateway: metric `latency_ms` at or above 2000.0, 09:40–10:30 UTC

## The trap

Worker duration rises right after a deploy that makes prompts longer; the gateway's metrics and logs and the worker's traces are missing, so provider slowness and the deploy cannot be separated. INCONCLUSIVE is correct.

## Run it

```powershell
# live (uses your Claude Code login)
$env:LLM_BACKEND="claude_code"; python -m eval.run --scenarios a08_slow_unobservable --no-judge
```
