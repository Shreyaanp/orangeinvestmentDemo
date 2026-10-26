# Multi-agent production-incident investigator

A team of AI agents that investigates production incidents for a WhatsApp AI banking assistant.
Given an incident ticket, it queries logs, metrics, deploys, code diffs, service dependencies, past
incidents and single user conversations. It returns ranked root-cause hypotheses with evidence for
and against, a confidence, and recommended actions, or an honest **INCONCLUSIVE** when the evidence
isn't there. A single-agent baseline with the same tools is included for comparison.

Built on **Google ADK**, with Claude (Sonnet 5.5 and Opus 5.5) through the Claude Agent SDK.

## Deliverables

| asked for | where |
|---|---|
| Runnable implementation and setup | this README: [Install](#install), [Use](#use), [Test](#test) |
| Architecture diagram and agent coordination | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| Synthetic incident dataset | [scenarios/README.md](scenarios/README.md): all 37 cases (33 synthetic, 4 real-telemetry RCAEval) with the command to run each; design in [docs/SCENARIOS.md](docs/SCENARIOS.md) |
| Automated tests | `tests/` (507 offline tests); [tests/REQUIREMENTS.md](tests/REQUIREMENTS.md) maps each assignment requirement to its test |
| Evaluation results, multi-agent vs single-agent | how they differ: [README](#our-method-versus-the-single-agent-baseline); numbers: [docs/RESULTS.md](docs/RESULTS.md); raw scores in `results/` |
| Technical note (500 words or fewer) | [docs/TECHNICAL_NOTE.md](docs/TECHNICAL_NOTE.md) |
| Coding-assistant transcript | submitted separately |
| Demo video | [Google Drive](https://drive.google.com/file/d/1-vBGNs02nNVkauwpGR-Fx01MU4GpX5MD/view?usp=drivesdk) |

## Install

You need Python 3.13 or newer. Live model runs also need [Claude Code](https://claude.com/claude-code)
installed and logged in; nothing else does.

```bash
git clone https://github.com/Shreyaanp/orangeinvestmentDemo.git
cd orangeinvestmentDemo
python -m venv .venv
source .venv/bin/activate          # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -e ".[dev]"            # about 1.5 minutes
```

On Windows, keep the venv on a short path (for example `C:\venvs\incident`) to avoid path-length
errors, and set `$env:PYTHONIOENCODING="utf-8"` so the demo output prints correctly.

## Use

### 1. Watch an investigation (no key, no tokens)

```bash
python -m eval.demo                                    # replays a recorded live run of scenario a01
python -m eval.demo --pace 0.3                         # the same, slow enough to follow
python -m eval.demo rca_re2ob_checkoutservice_cpu_1    # real recorded telemetry (RCAEval)
python -m eval.demo s05_poison_message                 # any scenario with a recorded run
```

It prints six sections:
1. the world the agents can query;
2. the ticket;
3. each agent step as it happens;
4. the answer;
5. the hidden answer key;
6. the score.

It also writes `results/demo/<scenario>/walkthrough.html` locally, with every prompt, reply, model,
limit, evidence item and metric. A finished example for a01 is in
[docs/a01_walkthrough.html](docs/a01_walkthrough.html). GitHub shows HTML as source, so download it
and open it in a browser.

### 2. Run it live

```bash
python -m eval.demo a03_poison_buttons --live          # one narrated live investigation
python -m eval.run --scenarios s02 --systems multi baseline   # both systems, scored
```

Live runs use your Claude Code login. Claude Code also accepts an `ANTHROPIC_API_KEY`, which should
let you bring your own key; this project has not tested that.

### 3. Evaluate

```bash
python -m eval.run --systems multi baseline --runs 1   # every scenario, both systems
python -m eval.run --scenarios s01 --variant rename     # metamorphic variant: shift, rename, shuffle, herring, drop
```

Each run writes `summary.md`, `scores.jsonl` and per-run traces to `results/<name>/`. The metrics:
- root-cause accuracy;
- a weighted score, in which a confidently wrong answer costs more than abstaining;
- evidence grounding: the hallucinated-evidence rate and the share of decisive evidence cited;
- tool calls, LLM calls, tokens and latency.

`--systems hybrid` runs one investigator followed by the critic's verification.

### 4. As a service

```bash
LLM_BACKEND=replay uvicorn incident.api:app
curl -X POST localhost:8000/investigations -H 'content-type: application/json' \
     -d '{"scenario_id":"s02_pool_vs_deploy","system":"multi"}'
curl localhost:8000/investigations/<run_id>            # the report; add /trace for every step
```

Settings come from environment variables:
- `LLM_BACKEND`: `claude_code`, `replay` or `fake`.
- `API_KEY`: turns on `X-API-Key` authentication.
- `MAX_CONCURRENT_RUNS`, `RUN_TIMEOUT_S`, `LLM_CONCURRENCY`.
- `LLM_MODEL_<ROLE>` and `LLM_EFFORT_<ROLE>`: override the model or effort for one role.

### 5. Real-infrastructure adapters, against a local mock

```bash
python src/scripts/demo_mock_infra.py s03_config_not_deploy --rate-limit 5
```

The adapters (`src/incident/adapters`) pull an incident window into the same dataset format:
- Datadog logs and metrics;
- GitHub deployments, Actions runs and diffs;
- GCP audit logs;
- CloudFormation events.

`tests/mockworld/` serves those APIs locally, so the adapters can be shown without credentials.

## Test

```bash
python src/scripts/gate.py        # the full quality gate (CI runs it too)
python -m pytest -q           # 507 offline tests: a fake model, no network
python -m eval.validate       # proves every generated scenario is solvable with the agents' tools
```

The gate runs ruff, strict mypy and the import-linter layer rules, then:
- size budgets;
- a check that runtime code can never read an answer key;
- a check that every requirement has a test;
- the tests.

The golden tests replay recorded live runs and require the same report.

## How it works

1. The orchestrator (a custom ADK `BaseAgent`, with control flow in plain Python) asks a planner to
   split the ticket into tasks.
2. Observability and Dependency specialists run those tasks in parallel through typed tools. The
   tools have timeouts, bounded retries and injected faults.
3. Every fact must quote a real tool result before it enters the shared evidence ledger. This check
   is code, not a prompt.
4. Reasoning proposes competing hypotheses, code computes their confidence, and a Critic challenges
   them. Its objections become new tasks. The loop is capped at 3 rounds, 70 tool calls, 600k tokens
   and 420 s.
5. Reporting writes the report; status, confidence, and facts versus assumptions are computed by
   code.

Optionally, a system catalogue and an incident memory (a SQLite graph, with keyword or hybrid
BM25 + embedding + rerank retrieval) give the team what it already knows. Past incidents enter only as
labelled hints, never as evidence.

Diagrams: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). The worlds being investigated:
[docs/SCENARIOS.md](docs/SCENARIOS.md).

## Our method versus the single-agent baseline

Both systems get the same ticket, the same tools, the same limits and the same model family, and
their answers pass through the same grounding and scoring code. Only the structure differs, so the
comparison is fair.

| | single-agent baseline | multi-agent team (our method) |
|---|---|---|
| Who investigates | one agent (Opus 5.5) plans, queries and concludes in a single pass | a planner splits the ticket into tasks; Observability and Dependency specialists (Sonnet 5.5) run them in parallel |
| Context | one model holds every tool result it fetched | specialists write facts into a shared evidence ledger; Reasoning, the Critic and Reporting (Opus 5.5) work from that ledger |
| Competing explanations | whatever the one agent considers | Reasoning must rank competing hypotheses, with evidence for and against each |
| Challenge and feedback | none: one pass, then the answer | the Critic challenges the leading hypothesis; its objections become new tool tasks for another round (up to 3) |
| Verdict and confidence | computed by the same code from its grounded evidence | the same code, after the extra evidence rounds |
| Typical cost (measured) | about 35k-75k tokens, 1.5-4.5 minutes | about 220k-515k tokens, 2.5-8 minutes |

**What the measurements show** (single runs per case; details in [docs/RESULTS.md](docs/RESULTS.md)):
- **Accuracy:** after calibration the two tied (0.83 on 12 scenarios). On the development set
  before calibration the baseline was ahead.
- **Wrong answers:** on held-out cases the team was never confidently wrong; the baseline was
  wrong twice.
- **Evidence:** the team cited all the decisive evidence (1.0); the baseline cited 0.83 of it.
- **Cost:** the team costs 4-8x more tokens and more time. When it misses, it usually abstains
  with the right component ranked first, because the Critic's objections lower its confidence.

So the team trades cost for answers that are better evidenced and less often confidently wrong. It
is not more accurate. A third option, `--systems hybrid`, keeps the baseline's single investigator
and adds the team's Critic and verification round; it is in [docs/RESULTS.md](docs/RESULTS.md).

## Data

No incident is hand-written. Answer keys (`truth.json`) are read only by `tests/eval/`.
- **25 service-level scenarios** (`s01`-`s19`, `f01`-`f06`), from a causal simulator.
- **8 message-level scenarios** (`a01`-`a08`), from an event simulator of the WhatsApp stack: webhook,
  SQS, Lambda worker, Redis, LLM, broker and account-aggregator APIs, and sender. A real git repo with
  CI and diffs sits behind it.
- **4 RCAEval cases** (`scenarios/rcaeval/`), with real recorded telemetry from a public benchmark: no
  deploys to blame, and a ticket that names no service. One case has been run live, and all four
  configurations found the cause. Details and limits:
  [docs/RESULTS.md](docs/RESULTS.md#real-telemetry-rcaeval).

Every scenario folder has a `README.md` with the ticket, the data, the answer and the trap. They are
generated by `python -m eval.describe`.

## Layout

```
src/
  incident/       the investigator: agents/, tools/, orchestrator, baseline, hybrid, state, scoring,
                  grounding, llm, memory, knowledge, retrieval, api, sim/ (simulators), adapters/
  scripts/        quality gate, scenario generator, RCAEval importer, Claude Code hooks
tests/
  eval/           evaluation harness, demo, metrics, judge, validator (the only code that reads
                  answer keys); run as `python -m eval.<module>`
  mockworld/      local mock of Datadog, GitHub, GCP and CloudFormation APIs
  harness/, core/, orch/, tools/, sim/, adapters/, api/, golden/   the offline tests
  REQUIREMENTS.md each assignment requirement and the test that proves it
scenarios/        all incident data; README.md lists every case. <id>/{data.json, truth.json, README.md}
tapes/            recorded model runs, so the demo and the golden tests replay offline
results/          score files behind docs/RESULTS.md
docs/             architecture, scenarios, results, technical note
```

## How this was built with Claude Code

The code was written with Claude Code, inside guard-rails that live in this repository:

| piece | where | what it enforces |
|---|---|---|
| Project rules | `CLAUDE.md` | No per-scenario hardcoding. Answer keys are read only by `tests/eval/`. Agents exchange typed messages. Every loop is capped. Tests run offline. No commit without the user asking |
| Hooks | `.claude/settings.json`, `src/scripts/hooks.py` | Each edited Python file is formatted and linted. Edits to any `truth.json` are blocked. `git commit` is blocked while the gate fails |
| Skills | `.claude/skills/` | Checklists loaded on demand: `add-scenario`, `add-agent`, `run-eval`, `pre-commit-gate` |
| Quality gate | `src/scripts/gate.py`, CI | Lint, strict types, layer rules, size budgets, answer-key isolation, requirement-to-test coverage |
| Offline model | fake backend, recorded tapes | Agent logic is tested without model calls, and live runs replay exactly |
| Parallel work | background agents, separate sessions | Live evaluations and studies ran in the background. Independent review sessions checked the work |

The conversation transcript is submitted separately.

## Limitations and external dependencies

- **Model access.** Live runs use a Claude Code login and its quota. Hosting live runs on a
  personal subscription may not be permitted by the terms of use. A native API-key backend
  (`LLM_BACKEND=api`) is **not implemented**; replay mode needs no model at all.
- **Synthetic data, mostly.** The simulators encode our model of failures. The 4 RCAEval cases are
  real telemetry, but the results show behaviour on these 37 cases, not on arbitrary production
  systems.
- **Small samples.** Most results are single runs per case, with some LLM-judge noise. Read the
  differences as directional.
- **Cost and speed.** A multi-agent run takes 2.5-8 minutes and about 220k-515k tokens, against 35k-75k for
  the single agent. Most of that is input, because each step re-sends the evidence gathered so far.
- **Own incidents.** The API and the demo take a scenario id. To investigate your own incident, put
  its data in the same `data.json` format under `scenarios/`. The adapters were tested only against
  the local mock, never a real account, and there is no CloudWatch or SQS adapter.
- **Grounding checks authenticity, not logic.** It proves that a quoted fact exists in a tool result.
  Whether the inference is sound is the Critic's job.
- **Memory and retrieval.** Live-tested once on 3 cases (in [docs/RESULTS.md](docs/RESULTS.md)).
  Hybrid retrieval needs `pip install .[retrieval]` (fastembed/onnxruntime, which has no Python 3.15
  wheels). It lifts recall@1 from 0.00 to 0.37 on hard queries, which is still weak.
- **Not implemented:** live drill-down tools against real infrastructure, durable queues or workflow
  engines (the board is checkpointed to disk instead), and a front end.
