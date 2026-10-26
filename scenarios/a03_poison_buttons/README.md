# a03_poison_buttons

World: v2 app world (message-level simulation of a WhatsApp banking stack). Expected outcome: **ANSWER**.

## The ticket (all the agents are told)

> Users who tap the quick-reply buttons ('Check balance', 'My orders') get no answer at all. Typed messages work. Since roughly 10:35 UTC.

Reported 2026-10-21 11:08 UTC.

## What the data holds (`data.json`)

- Window: 2026-10-21 10:00 to 11:30 UTC (90 min)
- Services (9): wa-webhook, worker, redis-session, llm-gateway, rds-postgres, broker-api, aa-api, sender, whatsapp-api
- 3,234 log lines, 34 metric series, 4 changes, 3 past incidents
- 1,801 WhatsApp conversations traced end to end, 4 git commits with diffs

| time (UTC) | kind | service | ref | note |
|---|---|---|---|---|
| 10:12 | deploy | wa-webhook | 5cfbaa3 | webhook: log the message type on enqueue |
| 10:33 | deploy | worker | 2af8a26 | feat: support WhatsApp list replies |
| 10:58 | deploy | worker | b0fcb97 | prompt: friendlier tone |
| 11:20 | deploy | worker | 638d440 | docs: describe the session cache |

## Answer key (spoiler, from `truth.json`; only `tests/eval/` reads it)

**F1 (primary)**: `worker` / `code_regression_poison_message`, onset 10:33 UTC.

A worker deploy changed parse_message to read interactive['list_reply']; button replies have no such key, so every interactive message raises KeyError, is retried by SQS three times and lands in the dead-letter queue.

Decisive evidence a correct report should cite:

- worker: the change whose ref contains `2af8a26`, 10:33–11:30 UTC
- worker: ERROR logs containing `KeyError: 'list_reply'`, 10:33–11:30 UTC
- sqs-inbound: metric `dlq_depth` at or above 5.0, 10:33–11:30 UTC
- worker: the commit touching `src/worker.py`, 10:33–11:30 UTC

## The trap

A short LLM latency blip overlaps the deploy; the overall error rate stays low because only ~5% of messages are button taps.

## Run it

```powershell
# live (uses your Claude Code login)
$env:LLM_BACKEND="claude_code"; python -m eval.run --scenarios a03_poison_buttons --no-judge
```
