---
name: add-scenario
description: Add a new synthetic incident scenario (data.json + truth.json) with its traps, using the project's checklist. Use when asked to create or extend test incidents.
---

# Add a scenario

1. Pick ONE primary trap type: red-herring deploy, config change outside deploy history, clock skew, contradictory logs vs metrics, stale history, tool timeout on the key tool, truncated result, insufficient evidence, concurrent causes, prompt injection in logs. Mix across the set; never two identical.
2. Create `scenarios/<id>/data.json`: incident report, logs, metrics, deploys, dependency graph, history, `faults` (declared failures per tool). Services are fintech themed (order routing, market data, auth/KYC, payments, portfolio).
3. Create `scenarios/<id>/truth.json`: root cause component, cause type, decisive evidence ids, `answerable` (bool), expected status (ANSWER or INCONCLUSIVE), and the trap description.
4. The decisive evidence must exist in `data.json`, unless `answerable` is false, in which case it must be absent. Run the scenario validator (once it exists).
5. Never reference the scenario id in `src/`. The gate will fail if you do.
6. Never edit an existing `truth.json` to make a run pass. A hook blocks it.
7. Add or update metamorphic variants only through the generator, not by hand-copying data.
