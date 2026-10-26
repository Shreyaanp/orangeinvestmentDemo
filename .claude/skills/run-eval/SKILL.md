---
name: run-eval
description: Run the multi-agent vs single-agent baseline evaluation and report results honestly. Use when asked to evaluate, benchmark, or compare the systems.
---

# Run the eval

1. Offline first: `python -m pytest -q` must pass (replay backend, no live LLM).
2. Live: `LLM_BACKEND=claude_code python -m eval.run --all --runs 3`. Model calls take about 10s each, so scenarios run concurrently with a cap.
3. Both systems use the same tool registry, budget, and report schema.
4. Report per scenario: correct/wrong/inconclusive, grounding %, tool calls, latency, input/output tokens, spread across runs.
5. Report raw accuracy AND the weighted score (+1 correct, -1 confidently wrong, +1 inconclusive on unanswerable, 0 inconclusive on answerable) side by side.
6. If the baseline wins somewhere, say so. Never change scenarios or truth to improve numbers. Fix the system.
7. Save results under `results/` with the date and backend.
