# a05_migration_ahead

World: v2 app world (message-level simulation of a WhatsApp banking stack). Expected outcome: **ANSWER**.

## The ticket (all the agents are told)

> Every balance and holdings question gets 'Sorry, I couldn't fetch that right now' since about 11:40 UTC. Order status questions still work.

Reported 2026-10-22 12:06 UTC.

## What the data holds (`data.json`)

- Window: 2026-10-22 11:00 to 12:30 UTC (90 min)
- Services (9): wa-webhook, worker, redis-session, llm-gateway, rds-postgres, broker-api, aa-api, sender, whatsapp-api
- 3,716 log lines, 34 metric series, 4 changes, 3 past incidents
- 1,801 WhatsApp conversations traced end to end, 5 git commits with diffs

| time (UTC) | kind | service | ref | note |
|---|---|---|---|---|
| 11:15 | deploy | worker | 44b6c31 | prompt: friendlier tone |
| 11:40 | migration | rds-postgres | cb475c7 | migration 002: rename holdings.qty to quantity |
| 12:08 | deploy | sender | 12892c0 | sender: send an explicit content-type header |
| 12:23 | deploy | wa-webhook | 6e551ea | webhook: log the message type on enqueue |

## Answer key (spoiler, from `truth.json`; only `tests/eval/` reads it)

**F1 (primary)**: `rds-postgres` / `schema_migration_ahead_of_code`, onset 11:40 UTC.

Migration 002 renamed holdings.qty to quantity, but the code change that reads the new column failed CI and was never deployed, so every portfolio query fails with 'column h.qty does not exist'.

Decisive evidence a correct report should cite:

- rds-postgres: the change whose ref contains `cb475c7`, 11:40–12:30 UTC
- worker: WARN logs containing `column h.qty does not exist`, 11:40–12:30 UTC
- rds-postgres: the commit touching `db/migrations/002_rename_qty.sql`, 11:40–12:30 UTC

## The trap

The matching code commit exists in git but its CI run failed, so it was never deployed; get_changes defaults to deploys and does not show the migration.

## Run it

```powershell
# live (uses your Claude Code login)
$env:LLM_BACKEND="claude_code"; python -m eval.run --scenarios a05_migration_ahead --no-judge
```
