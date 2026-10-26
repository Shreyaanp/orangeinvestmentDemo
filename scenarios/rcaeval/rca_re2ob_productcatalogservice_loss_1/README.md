# rca_re2ob_productcatalogservice_loss_1

World: RCAEval (real recorded telemetry, public benchmark). Expected outcome: **ANSWER**.

## The ticket (all the agents are told)

> Shop users report slow pages and some failed requests since about 18:20 UTC.

Reported 2024-01-15 18:28 UTC.

## What the data holds (`data.json`)

- Window: 2024-01-15 18:08 to 18:33 UTC (25 min)
- Services (12): adservice, cartservice, checkoutservice, currencyservice, emailservice, frontend, frontend-external, paymentservice, productcatalogservice, recommendationservice, redis, shippingservice
- 11,974 log lines, 72 metric series, 0 changes, 0 past incidents

## Answer key (spoiler, from `truth.json`; only `tests/eval/` reads it)

**F1 (primary)**: `productcatalogservice` / `network_packet_loss`, onset 18:20 UTC.

network packet loss injected into productcatalogservice (RE2-OB).

Decisive evidence a correct report should cite:

- productcatalogservice: metric `latency-90` at or above 0.0052, 18:20–18:33 UTC

## The trap

real telemetry (RE2-OB, network packet loss); no change events, no past incidents, per-second data averaged per minute

## Run it

```powershell
# live (uses your Claude Code login)
$env:LLM_BACKEND="claude_code"; python -m eval.run --root scenarios/rcaeval --scenarios rca_re2ob_productcatalogservice_loss_1 --no-judge
```
