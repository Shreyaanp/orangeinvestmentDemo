# rca_re2ob_currencyservice_delay_1

World: RCAEval (real recorded telemetry, public benchmark). Expected outcome: **ANSWER**.

## The ticket (all the agents are told)

> Shop users report slow pages and some failed requests since about 22:06 UTC.

Reported 2024-01-19 22:14 UTC.

## What the data holds (`data.json`)

- Window: 2024-01-19 21:54 to 22:19 UTC (25 min)
- Services (12): adservice, cartservice, checkoutservice, currencyservice, emailservice, frontend, frontend-external, paymentservice, productcatalogservice, recommendationservice, redis, shippingservice
- 16,122 log lines, 76 metric series, 0 changes, 0 past incidents

## Answer key (spoiler, from `truth.json`; only `tests/eval/` reads it)

**F1 (primary)**: `currencyservice` / `network_delay`, onset 22:06 UTC.

network delay injected into currencyservice (RE2-OB).

Decisive evidence a correct report should cite:

- currencyservice: metric `latency-90` at or above 0.0719, 22:06–22:19 UTC

## The trap

real telemetry (RE2-OB, network delay); no change events, no past incidents, per-second data averaged per minute

## Run it

```powershell
# live (uses your Claude Code login)
$env:LLM_BACKEND="claude_code"; python -m eval.run --root scenarios/rcaeval --scenarios rca_re2ob_currencyservice_delay_1 --no-judge
```
