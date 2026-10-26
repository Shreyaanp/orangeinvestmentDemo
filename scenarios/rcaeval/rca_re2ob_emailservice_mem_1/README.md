# rca_re2ob_emailservice_mem_1

World: RCAEval (real recorded telemetry, public benchmark). Expected outcome: **ANSWER**.

## The ticket (all the agents are told)

> Shop users report slow pages and some failed requests since about 07:11 UTC.

Reported 2024-01-17 07:19 UTC.

## What the data holds (`data.json`)

- Window: 2024-01-17 06:59 to 07:24 UTC (25 min)
- Services (12): adservice, cartservice, checkoutservice, currencyservice, emailservice, frontend, frontend-external, paymentservice, productcatalogservice, recommendationservice, redis, shippingservice
- 17,738 log lines, 71 metric series, 0 changes, 0 past incidents

## Answer key (spoiler, from `truth.json`; only `tests/eval/` reads it)

**F1 (primary)**: `emailservice` / `memory_exhaustion`, onset 07:11 UTC.

memory stress injected into emailservice (RE2-OB).

Decisive evidence a correct report should cite:

- emailservice: metric `mem` at or above 52238991.36, 07:11–07:24 UTC

## The trap

real telemetry (RE2-OB, memory stress); no change events, no past incidents, per-second data averaged per minute

## Run it

```powershell
# live (uses your Claude Code login)
$env:LLM_BACKEND="claude_code"; python -m eval.run --root scenarios/rcaeval --scenarios rca_re2ob_emailservice_mem_1 --no-judge
```
