from pathlib import Path

from eval.metrics import classify, decisive_recall, grounding, scenario_table, summary_table
from incident.messages import Claim, RankedHypothesis, Report, RunStats
from incident.sim.truth import Truth
from incident.state import Board

SCEN = Path(__file__).resolve().parents[2] / "scenarios"


def _truth(name: str) -> Truth:
    return Truth.model_validate_json((SCEN / name / "truth.json").read_text("utf-8"))


def _hyp(rank: int, component: str, cause: str = "x") -> RankedHypothesis:
    return RankedHypothesis(
        rank=rank, hypothesis_id=f"H{rank}", statement=f"{component} {cause}", component=component,
        cause_type=cause, score=1.0, confidence=0.8, label="high", supporting=[], contradicting=[],
    )  # fmt: skip


def _report(status: str, *hyps: RankedHypothesis, facts: int = 0, assumptions: int = 0) -> Report:
    claim = Claim(text="c", evidence_ids=["E-001"])
    return Report(
        status=status, status_reason="", summary="", hypotheses=list(hyps),  # type: ignore[arg-type]
        facts=[claim] * facts, assumptions=[claim] * assumptions, unresolved=[], actions=[], stats=RunStats(),
    )  # fmt: skip


async def test_single_cause_outcomes() -> None:  # covers: R16
    t = _truth("s01_bad_deploy")  # component order-router
    assert await classify(_report("ANSWER", _hyp(1, "order-router")), t, False) == "correct"
    assert (
        await classify(_report("ANSWER", _hyp(1, "web-app"), _hyp(2, "order-router")), t, False)
        == "wrong"
    )
    assert await classify(_report("INCONCLUSIVE", _hyp(1, "order-router")), t, False) == "abstained"
    assert await classify(_report("ANSWER"), t, False) == "abstained"  # nothing to judge


async def test_two_cause_scenario_needs_both_with_primary_first() -> None:  # covers: R16
    t = _truth("s12_two_causes")  # primary orchestrator, secondary msg-delivery
    both = _report("ANSWER", _hyp(1, "orchestrator"), _hyp(2, "msg-delivery"))
    assert await classify(both, t, False) == "correct"
    assert await classify(_report("ANSWER", _hyp(1, "orchestrator")), t, False) == "partial"
    swapped = _report("ANSWER", _hyp(1, "msg-delivery"), _hyp(2, "orchestrator"))
    assert await classify(swapped, t, False) == "partial"  # found both, wrong leader
    assert await classify(_report("ANSWER", _hyp(1, "web-app")), t, False) == "wrong"


async def test_abstaining_is_right_only_on_the_unanswerable_scenario() -> None:  # covers: R13, R16
    t = _truth("s11_insufficient")
    assert await classify(_report("INCONCLUSIVE"), t, False) == "correct"
    assert await classify(_report("ANSWER", _hyp(1, "portfolio-svc")), t, False) == "wrong"


def test_grounding_metrics() -> None:  # covers: R12, R16
    b = Board(incident_text="x")
    b.rejected += ["T1: excerpt not in tc-01: ['x']", "H1.supporting: unknown evidence id E-9"]
    halluc, facts = grounding(_report("ANSWER", facts=3, assumptions=1), b)
    assert halluc == 1.0 and facts == 0.75  # unknown-id links are not evidence hallucination
    assert grounding(_report("ANSWER"), Board(incident_text="x")) == (0.0, 1.0)


def test_decisive_recall_is_none_when_unanswerable() -> None:  # covers: R16
    assert (
        decisive_recall(
            _report("INCONCLUSIVE"), Board(incident_text="x"), _truth("s11_insufficient")
        )
        is None
    )
    assert (
        decisive_recall(_report("ANSWER"), Board(incident_text="x"), _truth("s01_bad_deploy"))
        == 0.0
    )


def test_tables_render_both_systems() -> None:  # covers: R16
    from eval.metrics import RunScore

    def s(system: str, outcome: str, score: float) -> RunScore:
        return RunScore(
            scenario="s01", system=system, run=1, expected="ANSWER", status="ANSWER",
            outcome=outcome, score=score, accuracy=max(score, 0.0), tool_calls=4, tokens=1000,
        )  # type: ignore[arg-type]  # fmt: skip

    rows = [s("multi", "correct", 1.0), s("baseline", "wrong", -1.0)]
    text = summary_table(rows)
    assert "| multi | 1 | 1.0 | 1.0 |" in text and "| baseline | 1 | 0.0 | -1.0 |" in text
    assert "correct(+1.0)" in scenario_table(rows) and "wrong(-1.0)" in scenario_table(rows)


def test_results_document_is_built_from_score_files(tmp_path: Path) -> None:  # covers: R16
    from eval.metrics import RunScore
    from eval.report import build

    row = RunScore(
        scenario="s01", system="multi", run=1, expected="ANSWER", status="ANSWER",
        outcome="correct", score=1.0, accuracy=1.0, tool_calls=3, tokens=500,
    )  # fmt: skip
    f = tmp_path / "scores.jsonl"
    f.write_text(row.model_dump_json() + "\n", encoding="utf-8")
    doc = build([f"First look|a note|{f}"])
    assert "## First look" in doc and "a note" in doc and "| multi | 1 | 1.0 | 1.0 |" in doc
    assert f"`{f}` (1 runs)" in doc
