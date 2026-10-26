"""The opt-in lean profile: digest tools for observability, compact ledgers, memoised tool calls."""

import json
from pathlib import Path

from team import Team

from incident.agents.common import Ctx, prompt_text
from incident.agents.tools import tools_for
from incident.agents.views import evidence_lines
from incident.llm import LlmFactory
from incident.messages import EvidenceDraft
from incident.orchestrator import investigate
from incident.state import Board, Limits
from incident.tools.store import Store
from incident.trace import Trace

SCEN = Path(__file__).resolve().parents[2] / "scenarios"


async def _tools_seen(lean: bool) -> dict[str, set[str]]:
    team, seen = Team(), {"observability": set(), "dependency": set(), "baseline": set()}

    def spy(key: str, n: int, system: str, prompt: str) -> str:
        role = key.split("/")[0]
        if role in seen:
            seen[role] |= {t for t in ("get_anomalies", "get_log_patterns") if f"- {t}(" in prompt}
        return team(key, n, system, prompt)

    store = Store.load(SCEN / "s01_bad_deploy")
    await investigate(store, LlmFactory("fake", script=spy), limits=Limits(lean=lean))
    return seen


async def test_digest_tools_are_offered_only_in_the_lean_profile() -> None:  # covers: R4
    default, lean = await _tools_seen(False), await _tools_seen(True)
    assert not default["observability"]
    assert lean["observability"] == {"get_anomalies", "get_log_patterns"}
    assert not lean["dependency"]  # only the agent that reads telemetry gets them


def test_lean_prompt_addenda_exist_and_default_prompts_are_untouched() -> None:  # covers: R2
    assert "get_anomalies" in prompt_text("observability", lean=True)
    assert "get_anomalies" not in prompt_text("observability")
    assert prompt_text("planner", lean=True) == prompt_text("planner")  # no addendum, no change


def test_the_lean_ledger_folds_near_duplicates_and_drops_quotes() -> None:  # covers: R2
    b = Board(incident_text="x")
    for claim in (
        "order-router returned unhandled exception KeyError limit_price in place_order",
        "order-router returned an unhandled exception KeyError limit_price in place_order",
        "web-app calls to order-router failed with 503",
    ):
        b.add_evidence(
            EvidenceDraft(kind="FACT", claim=claim, excerpt="LONG QUOTE", service="x"),
            "observability",
            1.0,
            [],
        )
    full, lean = evidence_lines(b), evidence_lines(b, digest=True)
    assert full.count("\n") == 2 and "LONG QUOTE" in full
    assert lean.count("\n") == 1 and "LONG QUOTE" not in lean and "(also E-" in lean
    assert len(lean) < len(full)


async def test_repeated_tool_calls_are_memoised_in_the_lean_profile_only() -> None:  # covers: R9
    for lean in (False, True):
        board = Board(incident_text="x", limits=Limits(lean=lean))
        ctx = Ctx(
            board=board,
            store=Store.load(SCEN / "s01_bad_deploy"),
            factory=LlmFactory("fake"),
            trace=Trace(),
        )
        tool = tools_for(["query_logs"], ctx, "T1")[0]
        first = await tool.run_async(args={"level": "ERROR", "limit": 3}, tool_context=None)
        again = await tool.run_async(
            args={"limit": 3, "level": "ERROR"}, tool_context=None
        )  # same, reordered
        assert board.usage.tool_calls == (1 if lean else 2)
        assert (again.get("cached") is True) == lean
        assert again["items"] == first["items"]
        assert (
            again["call_id"] == first["call_id"]
        ) == lean  # a cached answer cites the original call


async def test_a_lean_investigation_still_completes_and_reports() -> None:  # covers: R1, R11
    store = Store.load(SCEN / "s01_bad_deploy")
    out = await investigate(store, LlmFactory("fake", script=Team()), limits=Limits(lean=True))
    assert out.report.status == "ANSWER" and out.report.hypotheses[0].component == "order-router"
    json.loads(out.report.model_dump_json())
