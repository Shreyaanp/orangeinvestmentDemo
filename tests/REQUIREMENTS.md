# Assignment requirements and the test that proves each (the quality gate fails if a row has no test)

| # | Requirement | Component | Proving test |
|---|---|---|---|
| R1 | >=5 distinct agents (Orchestrator, Observability, Dependency, Reasoning, Critic, Reporting) | agents/ | per-agent contract test |
| R2 | Structured results between agents | messages.py (pydantic) | schema rejects free text |
| R3 | Genuine collaboration | critic challenge -> new tasks | golden trace: challenge adds a tool call absent in round 1 |
| R4 | Tools for logs, metrics, changes, dependencies, past incidents (plus 3 message-level and 2 digest tools), structured I/O | tools/ | per-tool I/O tests |
| R5 | Tool errors/timeouts/partials | tool wrapper + fault injection | fault matrix: tool x failure type |
| R6 | Parallel execution | task DAG waves (asyncio.gather) | two 1s tasks finish <1.5s |
| R7 | Shared state + task deps | blackboard | dependent never runs before prerequisite |
| R8 | Feedback loop for more evidence | critic loop | round 1 insufficient, round 2 resolves |
| R9 | Bounded retries/limits/termination | budget guard | property test: any fault sequence terminates within caps |
| R10 | Recovery from agent/tool failure | orchestrator | kill agent mid-run -> still a report |
| R11 | Ranked hypotheses, +/- evidence, confidence, actions | report schema | golden report |
| R12 | Facts vs assumptions | ledger `kind` | validator rejects unlabeled claims |
| R13 | Inconclusive outcome | termination logic | unanswerable scenario -> INCONCLUSIVE |
| R14 | >=10 incidents w/ misleading, conflicting, failing tools | scenarios/ | scenario linter: trap-type mix |
| R15 | Single-agent baseline, same tools | src/incident/baseline.py | identical tool registry check |
| R16 | Accuracy, grounding, tool calls, latency, tokens | tests/eval/ | metrics unit tests |
| R17 | No hardcoded answers | import-linter + grep | CI fails on ground-truth/scenario-id refs in agents/tools |
| R18 | Runnable + setup | README | CI installs the package, runs the gate and the tests |
| R19 | Diagram, <=500-word note, transcript | docs/ | word-count check |
| R20 | Document incomplete work | README Limitations | review checklist |
