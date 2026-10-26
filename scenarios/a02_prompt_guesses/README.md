# a02_prompt_guesses

World: v2 app world (message-level simulation of a WhatsApp banking stack). Expected outcome: **ANSWER**.

## The ticket (all the agents are told)

> Several users complain the bot told them a portfolio value that is clearly wrong (one says 'it said 2.1 lakh, the app says 2.6 lakh'). Started this morning, maybe around 09:40 UTC. Error-rate and latency dashboards are all green.

Reported 2026-10-21 10:10 UTC.

## What the data holds (`data.json`)

- Window: 2026-10-21 09:00 to 10:30 UTC (90 min)
- Services (9): wa-webhook, worker, redis-session, llm-gateway, rds-postgres, broker-api, aa-api, sender, whatsapp-api
- 3,390 log lines, 34 metric series, 4 changes, 3 past incidents
- 1,882 WhatsApp conversations traced end to end, 4 git commits with diffs

| time (UTC) | kind | service | ref | note |
|---|---|---|---|---|
| 09:24 | deploy | worker | 9acee2f | refactor: AA client uses a shared http session |
| 09:36 | deploy | worker | 387c386 | prompt v13: always give the user a concrete answer |
| 10:00 | deploy | worker | f7c5291 | prompt: friendlier tone |
| 10:15 | deploy | wa-webhook | ba4a4bb | webhook: log the message type on enqueue |

## Answer key (spoiler, from `truth.json`; only `tests/eval/` reads it)

**F1 (primary)**: `worker` / `bad_prompt_release`, onset 09:36 UTC.

Prompt v13 tells the model to estimate when a tool result is missing; when the portfolio tool fails (a pre-existing ~8% intermittent RDS connection error) the model now invents a portfolio value instead of apologising.

Decisive evidence a correct report should cite:

- worker: the change whose ref contains `387c386`, 09:36–10:30 UTC
- worker: the commit touching `prompts/answer.txt`, 09:36–10:30 UTC
- worker: conversations containing `Your portfolio is worth` with a failed tool call, 09:36–10:30 UTC

## The trap

Error rates and latency are unchanged, and the RDS errors were there all day (not new). Only the conversation records show answers given after a failed tool call; the cause is the prompt release, not the database.

## Run it

```powershell
# live (uses your Claude Code login)
$env:LLM_BACKEND="claude_code"; python -m eval.run --scenarios a02_prompt_guesses --no-judge
```
