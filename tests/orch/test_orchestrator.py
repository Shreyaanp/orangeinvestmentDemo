import asyncio
import json
import time
from pathlib import Path

import pytest
from team import Team

from incident import orchestrator
from incident.agents.common import Ctx
from incident.baseline import investigate_baseline
from incident.llm import LlmFactory, Tape
from incident.messages import SpecialistResult
from incident.orchestrator import investigate
from incident.state import Limits
from incident.tools.store import Store

SCEN = Path(__file__).resolve().parents[2] / "scenarios"


def _run(team: Team, scenario: str = "s01_bad_deploy", **kw):  # type: ignore[no-untyped-def]
    store = Store.load(SCEN / scenario)
    return investigate(store, LlmFactory("fake", script=team), **kw)


async def test_end_to_end_happy_path() -> None:  # covers: R1, R2, R7, R11, R12
    team = Team()
    out = await _run(team)
    r, b = out.report, out.board
    assert r.status == "ANSWER" and r.hypotheses[0].component == "order-router"
    assert r.hypotheses[0].confidence >= 0.45 and r.hypotheses[0].label in ("medium", "high")
    # every cited id exists; facts and assumptions are separated by construction
    ids = set(b.evidence)
    assert all(i in ids for c in r.facts for i in c.evidence_ids) and not r.assumptions
    assert all(i in ids for a in r.actions for i in a.evidence_ids) and r.actions
    assert r.stats.tool_calls == 2 and r.stats.llm_calls >= 8 and r.stats.rounds == 1
    assert {t.agent for t in b.tasks.values()} == {"observability", "dependency"}
    # every agent role took part
    roles = {k.split("/")[0].split("#")[0] for k in team.log}
    assert roles == {"planner", "observability", "dependency", "reasoning", "critic", "reporting"}


async def test_specialists_run_in_parallel(monkeypatch) -> None:  # type: ignore[no-untyped-def]  # covers: R6
    async def slow(ctx: Ctx, task) -> SpecialistResult:  # type: ignore[no-untyped-def]
        await asyncio.sleep(0.4)
        return SpecialistResult(summary="done", evidence=[])

    monkeypatch.setitem(orchestrator.SPECIALISTS, "observability", slow)
    monkeypatch.setitem(orchestrator.SPECIALISTS, "dependency", slow)
    t0 = time.monotonic()
    await _run(Team())
    assert time.monotonic() - t0 < 0.75  # two 0.4s tasks overlapped, not 0.8s in sequence


async def test_critic_challenge_creates_followup_work() -> None:  # covers: R3, R8
    team = Team(challenge_first=True)
    out = await _run(team)
    b = out.board
    follow = [t for t in b.tasks.values() if t.origin == "critic"]
    assert len(follow) == 1 and follow[0].status == "done" and follow[0].challenge_id == "C1"
    assert b.challenges["C1"].resolved and b.round == 2
    assert any(k.startswith(f"observability/{follow[0].id}") for k in team.log)
    assert out.report.stats.rounds == 2 and out.report.status == "ANSWER"


async def test_unresolved_challenge_lowers_confidence_when_rounds_run_out() -> (
    None
):  # covers: R8, R13
    team = Team(challenge_first=True)
    out = await _run(team, limits=Limits(max_rounds=1))
    assert out.board.round == 1 and not out.board.challenges["C1"].resolved
    assert any("unresolved critic challenge" in g.description for g in out.board.gaps)
    assert any("unresolved critic challenge" in u for u in out.report.unresolved)


async def test_tool_failures_become_gaps_and_cap_confidence() -> None:  # covers: R5, R10
    team = Team(metrics_for="redis-cache")
    out = await _run(team, scenario="s09_metrics_down")
    b = out.board
    assert b.usage.tool_attempts > b.usage.tool_calls  # retries happened
    assert any("query_metrics" in g.description for g in b.gaps)
    assert any("partial" in e.flags for e in b.evidence.values())
    assert out.report.status in ("ANSWER", "INCONCLUSIVE") and out.report.unresolved


async def test_agent_crash_is_contained_and_run_still_reports() -> None:  # covers: R10
    team = Team()
    team.crash = {"dependency"}
    out = await _run(team)
    failed = [t for t in out.board.tasks.values() if t.agent == "dependency"]
    assert failed and failed[0].status == "failed" and failed[0].attempts == 2
    assert any("failed" in g.description for g in out.board.gaps)
    assert out.report.status in ("ANSWER", "INCONCLUSIVE") and out.report.hypotheses


async def test_reasoning_failure_yields_an_honest_inconclusive_report() -> None:  # covers: R10, R13
    team = Team()
    team.garbage = {"reasoning", "reporting", "critic"}
    out = await _run(team)
    assert out.report.status == "INCONCLUSIVE" and not out.report.hypotheses
    assert "no supported hypothesis" in out.report.status_reason


async def test_invalid_json_is_repaired_once() -> None:  # covers: R2
    team = Team()
    seen = {"n": 0}

    def flaky(key: str, n: int, system: str, prompt: str) -> str:
        if key == "planner" and seen["n"] == 0:
            seen["n"] += 1
            return "not json at all"
        return team(key, n, system, prompt)

    store = Store.load(SCEN / "s01_bad_deploy")
    out = await investigate(store, LlmFactory("fake", script=flaky))
    assert seen["n"] == 1 and len(out.board.tasks) == 2  # planner recovered on the retry


async def test_budget_limits_stop_the_run_early() -> None:  # covers: R9
    out = await _run(Team(), limits=Limits(max_tool_calls=1))
    assert out.report.stats.tool_calls <= 2  # in-flight parallel calls finish; none after the cap
    assert "tool-call limit" in out.report.status_reason or out.board.budget_exceeded()


async def test_invalid_evidence_is_rejected_and_counted() -> None:  # covers: R12
    team = Team()

    def liar(key: str, n: int, system: str, prompt: str) -> str:
        if key.startswith("dependency") and n == 2:
            ev = {"kind": "FACT", "claim": "made up", "excerpt": "deploy rolled out 9999 nodes",
                  "source_call_id": "T2-01", "service": "web-app"}  # fmt: skip
            return json.dumps({"final": {"summary": "x", "evidence": [ev], "gaps": []}})
        return team(key, n, system, prompt)

    store = Store.load(SCEN / "s01_bad_deploy")
    out = await investigate(store, LlmFactory("fake", script=liar))
    assert any("excerpt not in" in r for r in out.board.rejected)
    assert all(
        e.service != "web-app" or e.author != "dependency" for e in out.board.evidence.values()
    )


async def test_replay_reproduces_a_run_exactly(tmp_path: Path) -> None:  # covers: R10
    team, tape = Team(challenge_first=True), tmp_path / "tape.jsonl"
    rec = Tape(tape, record=True)

    def recording(key: str, n: int, system: str, prompt: str) -> str:
        text = team(key, n, system, prompt)
        rec.put(key, n, text, 10, 5, "fake-model")
        return text

    first = await _run(Team(challenge_first=True)) if False else None  # noqa: SIM108
    store = Store.load(SCEN / "s01_bad_deploy")
    live = await investigate(store, LlmFactory("fake", script=recording))
    replayed = await investigate(
        Store.load(SCEN / "s01_bad_deploy"), LlmFactory("replay", tape=tape)
    )
    assert first is None
    assert replayed.report.model_dump(exclude={"stats"}) == live.report.model_dump(
        exclude={"stats"}
    )
    assert replayed.board.evidence.keys() == live.board.evidence.keys()


async def test_resume_does_not_redo_finished_work(tmp_path: Path) -> None:  # covers: R10
    store = Store.load(SCEN / "s01_bad_deploy")
    first = await investigate(store, LlmFactory("fake", script=Team()), run_dir=tmp_path)
    assert (tmp_path / "board.json").exists()
    team2 = Team()
    again = await investigate(
        Store.load(SCEN / "s01_bad_deploy"),
        LlmFactory("fake", script=team2),
        run_dir=tmp_path,
        resume=True,
    )
    assert not any(k.startswith(("observability", "dependency", "planner")) for k in team2.log)
    assert again.board.evidence.keys() == first.board.evidence.keys()


async def test_baseline_uses_same_tools_grounding_and_scoring() -> None:  # covers: R15
    store = Store.load(SCEN / "s01_bad_deploy")
    out = await investigate_baseline(store, LlmFactory("fake", script=Team()))
    r = out.report
    assert r.status == "ANSWER" and r.hypotheses[0].component == "order-router"
    assert r.stats.tool_calls == 1 and r.actions and r.stats.rounds == 0
    assert r.stats.models == {"claude-opus-5-5": r.stats.llm_calls}
    assert all(c.evidence_ids for h in r.hypotheses for c in h.supporting)


def test_claude_sessions_are_model_only() -> None:  # covers: R5
    from incident.llm import claude_options

    o = claude_options("sys", "claude-sonnet-5-5", "medium")
    assert o.tools == [] and o.mcp_servers == {} and o.strict_mcp_config is True
    assert o.setting_sources == [] and o.max_turns == 1 and o.effort == "medium"


def test_roles_use_pinned_sonnet_and_opus_and_runs_record_the_serving_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from incident.llm import LlmFactory

    f = LlmFactory("fake", script=lambda *_: "{}")
    obs, rea = f.llm("observability"), f.llm("reasoning")
    assert (obs.model, obs.effort) == ("claude-sonnet-5-5", "medium")
    assert rea.model == "claude-opus-5-5" and f.llm("baseline").model == "claude-opus-5-5"
    assert "haiku" not in str([f.llm(r).model for r in ("planner", "dependency", "critic")])
    monkeypatch.setenv("LLM_MODEL_CRITIC", "claude-sonnet-5-5")
    monkeypatch.setenv("LLM_EFFORT_CRITIC", "high")
    c = f.llm("critic")
    assert (c.model, c.effort) == ("claude-sonnet-5-5", "high")


async def test_a_clean_retry_resolves_the_gap_it_follows() -> None:  # covers: R5, R10
    from incident.agents.tools import tools_for
    from incident.models import ToolFault

    store = Store.load(SCEN / "s01_bad_deploy")
    store.data = store.data.model_copy(
        update={
            "tool_faults": [
                ToolFault(tool="query_metrics", kind="partial", on_calls=[1], max_results=1)
            ]
        }
    )
    from incident.state import Board
    from incident.trace import Trace

    board = Board(incident_text="x")
    ctx = Ctx(board=board, store=store, factory=LlmFactory("fake"), trace=Trace())
    ctx.board.add_gap("unrelated earlier gap")  # the old code popped inside a loop and crashed here
    tool = tools_for(["query_metrics"], ctx, "T9")[0]
    await tool.run_async(args={"service": "order-router"}, tool_context=None)
    assert board.open_gaps() == 2
    await tool.run_async(args={"service": "order-router"}, tool_context=None)
    assert [g.resolved for g in board.gaps] == [False, True]


async def test_tool_arguments_tolerate_explicit_nulls() -> None:  # covers: R5
    store = Store.load(SCEN / "s01_bad_deploy")
    args = {"service": "order-router", "metric": None, "start": None, "step_min": None}
    from incident.tools.guard import invoke

    out = await invoke(store, "query_metrics", args)
    assert out.ok and out.attempts == 1


async def test_quota_exhaustion_aborts_instead_of_being_contained() -> None:  # covers: R10
    import pytest

    from incident.protocol import QuotaError

    def out_of_quota(key: str, n: int, system: str, prompt: str) -> str:
        raise QuotaError("session limit")

    store = Store.load(SCEN / "s01_bad_deploy")
    with pytest.raises(
        QuotaError
    ):  # a result produced without quota would say nothing about the system
        await investigate(store, LlmFactory("fake", script=out_of_quota))


def test_quota_messages_are_recognised() -> None:  # covers: R10
    from incident.llm import QUOTA

    assert QUOTA.search("You've hit your session limit · resets 10pm (Asia/Kolkata)")
    assert QUOTA.search("Claude usage limit reached")
    assert not QUOTA.search("Reached maximum number of turns (1)")
