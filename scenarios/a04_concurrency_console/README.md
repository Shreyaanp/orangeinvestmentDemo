# a04_concurrency_console

World: v2 app world (message-level simulation of a WhatsApp banking stack). Expected outcome: **ANSWER**.

## The ticket (all the agents are told)

> Replies on WhatsApp are taking many minutes to arrive since about 09:45 UTC. Answers are correct when they come.

Reported 2026-10-22 10:10 UTC.

## What the data holds (`data.json`)

- Window: 2026-10-22 09:00 to 10:30 UTC (90 min)
- Services (9): wa-webhook, worker, redis-session, llm-gateway, rds-postgres, broker-api, aa-api, sender, whatsapp-api
- 3,629 log lines, 34 metric series, 5 changes, 3 past incidents
- 2,131 WhatsApp conversations traced end to end, 4 git commits with diffs

| time (UTC) | kind | service | ref | note |
|---|---|---|---|---|
| 09:19 | deploy | sender | f44ecf6 | sender: send an explicit content-type header |
| 09:37 | deploy | worker | 4466eaf | refactor: build the tool registry with dict() |
| 09:41 | config | worker | ct-7d3da4d | PutFunctionConcurrency worker ReservedConcurrentExecutions=1 (console, cost cap) |
| 09:58 | deploy | worker | 728d8a0 | prompt: friendlier tone |
| 10:14 | deploy | worker | 4d4dbb6 | docs: describe the session cache |

## Answer key (spoiler, from `truth.json`; only `tests/eval/` reads it)

**F1 (primary)**: `worker` / `concurrency_limit_config`, onset 09:41 UTC.

Someone set the worker Lambda's reserved concurrency to 1 from the console; one slot cannot keep up with ~24 messages/min at ~3s each, so SQS inbound backs up and replies wait minutes.

Decisive evidence a correct report should cite:

- worker: the change whose ref contains `ct-7d3da4d`, 09:41–10:30 UTC
- worker: metric `throttles` at or above 5.0, 09:41–10:30 UTC
- sqs-inbound: metric `oldest_age_s` at or above 120.0, 09:41–10:30 UTC

## The trap

A worker deploy lands four minutes earlier; the real change is a console configuration change (CloudTrail), not in git and only visible with kinds=config.

## Run it

```powershell
# live (uses your Claude Code login)
$env:LLM_BACKEND="claude_code"; python -m eval.run --scenarios a04_concurrency_console --no-judge
```
