"""Score one investigation against its answer key, and aggregate runs into comparison tables.

Outcome scoring: correct +1, partial +0.5, confidently wrong -1, abstained 0. On a scenario that
is genuinely unanswerable, abstaining is correct (+1) and answering is wrong (-1).
Plain accuracy (correct=1, partial=0.5) is always reported next to the weighted score.
"""

from collections import defaultdict
from typing import Literal

from eval.judge import same_cause
from incident.messages import RankedHypothesis, Report
from incident.models import Strict
from incident.sim.truth import Selector, Truth, TruthFault
from incident.state import Board

Outcome = Literal["correct", "partial", "wrong", "abstained"]
SCORE: dict[str, float] = {"correct": 1.0, "partial": 0.5, "wrong": -1.0, "abstained": 0.0}
ACCURACY: dict[str, float] = {"correct": 1.0, "partial": 0.5, "wrong": 0.0, "abstained": 0.0}


class RunScore(Strict):
    scenario: str
    system: str
    run: int
    expected: Literal["ANSWER", "INCONCLUSIVE"]
    status: Literal["ANSWER", "INCONCLUSIVE", "ERROR"]
    outcome: Outcome
    score: float
    accuracy: float
    top: str = ""
    hallucination_rate: float = 0.0
    dropped_claims: int = 0
    fact_share: float = 1.0
    decisive_recall: float | None = None
    tool_calls: int = 0
    tool_attempts: int = 0
    llm_calls: int = 0
    tokens: int = 0
    rounds: int = 0
    latency_s: float = 0.0
    error: str | None = None
    recalled: int = 0  # past incidents recalled from memory
    history_actions: int = 0  # candidate fixes taken from a confirmed past incident
    history_fix_right: bool | None = None  # did they come from an incident with the true cause


async def _matches(f: TruthFault, h: RankedHypothesis, use_llm: bool) -> bool:
    return await same_cause(
        f.component, f.cause_type, h.component, h.cause_type, h.statement, use_llm, f.description
    )


async def classify(report: Report, truth: Truth, use_llm: bool) -> Outcome:
    if truth.expected_status == "INCONCLUSIVE":
        return "correct" if report.status == "INCONCLUSIVE" else "wrong"
    if report.status == "INCONCLUSIVE" or not report.hypotheses:
        return "abstained"
    top3 = report.hypotheses[:3]
    primary = next(f for f in truth.faults if f.role == "primary")
    others = [f for f in truth.faults if f.role == "secondary"]
    lead_primary = await _matches(primary, top3[0], use_llm)
    lead_any = lead_primary or any([await _matches(f, top3[0], use_llm) for f in others])
    if not lead_any:
        return "wrong"
    found = [any([await _matches(f, h, use_llm) for h in top3]) for f in others]
    return "correct" if lead_primary and all(found) else "partial"


def _hit(sel: Selector, text: str, service: str | None) -> bool:
    low = text.lower()
    if sel.kind == "metric":
        return sel.metric is not None and sel.metric.lower() in low and service == sel.service
    return sel.contains.lower() in low


def decisive_recall(report: Report, board: Board, truth: Truth) -> float | None:
    """Share of the answer key's decisive evidence that the report actually cites."""
    if not truth.answerable:
        return None
    cited = {
        i
        for h in report.hypotheses
        for c in (*h.supporting, *h.contradicting)
        for i in c.evidence_ids
    }
    pieces = [
        (board.evidence[i], f"{board.evidence[i].excerpt} {board.evidence[i].claim}") for i in cited
    ]
    sels = [s for f in truth.faults for s in f.decisive]
    hits = [any(_hit(s, text, ev.service) for ev, text in pieces) for s in sels]
    return round(sum(hits) / len(sels), 3) if sels else None


def grounding(report: Report, board: Board) -> tuple[float, float]:
    bad = sum(1 for r in board.rejected if "unknown evidence id" not in r)
    total = len(board.evidence) + bad
    facts, assumed = len(report.facts), len(report.assumptions)
    return (bad / total if total else 0.0), (facts / (facts + assumed) if facts + assumed else 1.0)


async def score_run(
    scenario: str, system: str, run: int, report: Report, board: Board, truth: Truth, use_llm: bool
) -> RunScore:
    outcome = await classify(report, truth, use_llm)
    halluc, fact_share = grounding(report, board)
    s = report.stats
    top = report.hypotheses[0] if report.hypotheses else None
    return RunScore(
        scenario=scenario, system=system, run=run, expected=truth.expected_status,
        status=report.status, outcome=outcome, score=SCORE[outcome], accuracy=ACCURACY[outcome],
        top=f"{top.component}/{top.cause_type}" if top else "", hallucination_rate=round(halluc, 3),
        dropped_claims=report.dropped_claims, fact_share=round(fact_share, 3),
        decisive_recall=decisive_recall(report, board, truth), tool_calls=s.tool_calls,
        tool_attempts=s.tool_attempts, llm_calls=s.llm_calls, tokens=s.tokens_in + s.tokens_out,
        rounds=s.rounds, latency_s=s.elapsed_s,
    )  # fmt: skip


def failed_run(scenario: str, system: str, run: int, truth: Truth, err: str) -> RunScore:
    return RunScore(
        scenario=scenario, system=system, run=run, expected=truth.expected_status,
        status="ERROR", outcome="wrong" if truth.expected_status == "INCONCLUSIVE" else "abstained",
        score=0.0, accuracy=0.0, error=err,
    )  # fmt: skip


def _mean(xs: list[float]) -> float:
    return round(sum(xs) / len(xs), 3) if xs else 0.0


def summary_table(scores: list[RunScore]) -> str:
    by: dict[str, list[RunScore]] = defaultdict(list)
    for s in scores:
        by[s.system].append(s)
    head = (
        "| system | runs | accuracy | weighted score | wrong (confident) | abstained | "
        "hallucinated evidence | decisive evidence cited | tool calls | LLM calls | tokens | "
        "latency s |\n"
        "|---|---|---|---|---|---|---|---|---|---|---|---|\n"
    )
    rows = []
    for name, xs in sorted(by.items()):
        rec = [x.decisive_recall for x in xs if x.decisive_recall is not None]
        wrong = _mean([float(x.outcome == "wrong") for x in xs])
        absn = _mean([float(x.outcome == "abstained") for x in xs])
        rows.append(
            f"| {name} | {len(xs)} | {_mean([x.accuracy for x in xs])} | "
            f"{_mean([x.score for x in xs])} | "
            f"{wrong} | {absn} | {_mean([x.hallucination_rate for x in xs])} | {_mean(rec)} | "
            f"{_mean([x.tool_calls for x in xs])} | {_mean([x.llm_calls for x in xs])} | "
            f"{_mean([x.tokens for x in xs]):.0f} | {_mean([x.latency_s for x in xs])} |"
        )
    return head + "\n".join(rows)


def scenario_table(scores: list[RunScore]) -> str:
    systems = sorted({s.system for s in scores})
    head = (
        "| scenario | expected | "
        + " | ".join(systems)
        + " |\n|---|---|"
        + "---|" * len(systems)
        + "\n"
    )
    rows = []
    for scn in sorted({s.scenario for s in scores}):
        cells = []
        for sysname in systems:
            xs = [s for s in scores if s.scenario == scn and s.system == sysname]
            cells.append(" ".join(f"{x.outcome}({x.score:+.1f})" for x in xs) or "-")
        exp = next(s.expected for s in scores if s.scenario == scn)
        rows.append(f"| {scn} | {exp} | " + " | ".join(cells) + " |")
    return head + "\n".join(rows)
