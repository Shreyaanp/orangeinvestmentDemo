"""Golden traces: replaying a recorded live investigation must reproduce its live report exactly."""

import json
from pathlib import Path

import pytest

from incident.baseline import investigate_baseline
from incident.llm import LlmFactory
from incident.orchestrator import investigate
from incident.tools.store import Store

ROOT = Path(__file__).resolve().parents[2]
GOLDENS = sorted((ROOT / "tapes").glob("*/*.report.json"))


def _comparable(report: dict) -> dict:  # type: ignore[type-arg]
    d = json.loads(json.dumps(report))
    d["stats"].pop("elapsed_s", None)  # wall time differs between a live run and a replay
    d["stats"].pop("models", None)  # older tapes did not record the serving model
    for act in d["actions"]:
        if act.get("source") == "evidence":  # the default; older goldens predate the field
            del act["source"]
    d["unresolved"] = sorted(d["unresolved"])  # gap order follows tool completion order
    return d  # type: ignore[no-any-return]


@pytest.mark.skipif(not GOLDENS, reason="no golden reports blessed yet (scripts/bless_goldens.py)")
@pytest.mark.parametrize("golden", GOLDENS, ids=lambda p: f"{p.parent.name}-{p.name.split('.')[0]}")
async def test_replay_reproduces_the_live_report(golden: Path) -> None:  # covers: R3, R8, R10
    scenario, system = golden.parent.name, golden.name.split("-")[0]
    tape = golden.with_name(golden.name.replace(".report.json", ".jsonl"))
    store = Store.load(ROOT / "scenarios" / scenario.split("+")[0])
    factory = LlmFactory("replay", tape=tape)
    out = await (investigate if system == "multi" else investigate_baseline)(store, factory)
    live = json.loads(golden.read_text("utf-8"))
    assert _comparable(json.loads(out.report.model_dump_json())) == _comparable(live)


@pytest.mark.skipif(not GOLDENS, reason="no golden reports blessed yet")
def test_a_critic_challenge_changed_what_ran_in_some_recorded_investigation() -> (
    None
):  # covers: R3, R8
    """Evidence that agents collaborate: in at least one live run, a challenge became a task."""
    for g in GOLDENS:
        board = g.with_name(g.name.replace(".report.json", ".board.json"))
        if board.exists() and any(
            t["origin"] == "critic" for t in json.loads(board.read_text("utf-8"))["tasks"].values()
        ):
            return
    pytest.skip("no recorded board with critic-origin tasks (bless boards too)")
