"""Hybrid: one investigator with full context, then one critic round and its follow-ups."""

from pathlib import Path

from team import Team

from incident.hybrid import investigate_hybrid
from incident.llm import LlmFactory
from incident.tools.store import Store

SCEN = Path(__file__).resolve().parents[2] / "scenarios"


async def _run(team: Team):  # type: ignore[no-untyped-def]
    return await investigate_hybrid(
        Store.load(SCEN / "s01_bad_deploy"), LlmFactory("fake", script=team)
    )


async def test_approved_answer_needs_no_specialists() -> None:  # covers: R1, R15
    team = Team()
    out = await _run(team)
    assert out.report.status == "ANSWER" and out.report.hypotheses[0].component == "order-router"
    roles = {k.split("/")[0].split("#")[0] for k in team.log}
    assert roles == {"baseline", "critic"} and not out.board.tasks


async def test_critic_objection_runs_one_verification_round() -> None:  # covers: R7, R15
    team = Team(challenge_first=True)
    out = await _run(team)
    b, roles = out.board, {k.split("/")[0].split("#")[0] for k in team.log}
    assert {"baseline", "critic", "observability", "reasoning", "reporting"} <= roles
    assert [t.agent for t in b.tasks.values()] == ["observability"] and b.round == 2
    assert all(t.status == "done" for t in b.tasks.values())
    assert out.report.status == "ANSWER" and out.report.hypotheses[0].component == "order-router"
