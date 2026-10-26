# rca_re2ob_checkoutservice_cpu_1

World: RCAEval (real recorded telemetry, public benchmark). Expected outcome: **ANSWER**.

## The ticket (all the agents are told)

> Shop users report slow pages and some failed requests since about 21:36 UTC.

Reported 2024-01-15 21:44 UTC.

## What the data holds (`data.json`)

- Window: 2024-01-15 21:24 to 21:49 UTC (25 min)
- Services (12): adservice, cartservice, checkoutservice, currencyservice, emailservice, frontend, frontend-external, paymentservice, productcatalogservice, recommendationservice, redis, shippingservice
- 17,132 log lines, 72 metric series, 0 changes, 0 past incidents

## Answer key (spoiler, from `truth.json`; only `tests/eval/` reads it)

**F1 (primary)**: `checkoutservice` / `cpu_saturation`, onset 21:36 UTC.

CPU stress injected into checkoutservice (RE2-OB).

Decisive evidence a correct report should cite:

- checkoutservice: metric `cpu` at or above 0.6808, 21:36–21:49 UTC

## The trap

real telemetry (RE2-OB, CPU stress); no change events, no past incidents, per-second data averaged per minute

## Run it

```powershell
# live (uses your Claude Code login)
$env:LLM_BACKEND="claude_code"; python -m eval.run --root scenarios/rcaeval --scenarios rca_re2ob_checkoutservice_cpu_1 --no-judge
```
