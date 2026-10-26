import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "orch"))
from team import Team  # noqa: E402

from incident.llm import LlmFactory  # noqa: E402
from incident.memory import Memory  # noqa: E402
from incident.messages import Action, RankedHypothesis, Report, RunStats  # noqa: E402
from incident.models import Dataset, Edge, Topology  # noqa: E402
from incident.orchestrator import investigate  # noqa: E402
from incident.tools.guard import invoke  # noqa: E402
from incident.tools.store import Store  # noqa: E402

SCEN = Path(__file__).resolve().parents[2] / "scenarios"
WHEN = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
TOPO = Topology(
    services=["aa-sync", "postgres", "portfolio-consumer", "order-router", "broker-gateway"],
    edges=[
        Edge(caller="aa-sync", callee="postgres", weight=0.7),
        Edge(caller="order-router", callee="broker-gateway", weight=0.8),
    ],
    queues=[],
)


def _report(component: str, cause: str, status: str = "ANSWER", conf: float = 0.8) -> Report:
    top = RankedHypothesis(
        rank=1, hypothesis_id="H1", statement=f"{component} suffers {cause}", component=component,
        cause_type=cause, score=3.0, confidence=conf, label="high", supporting=[], contradicting=[],
    )  # fmt: skip
    act = Action(text="roll back", rationale="r", evidence_ids=["E-001"], priority="immediate")
    return Report(
        status=status, status_reason="", summary="", hypotheses=[top], facts=[], assumptions=[],  # type: ignore[arg-type]
        unresolved=[], actions=[act], stats=RunStats(),
    )  # fmt: skip


def _memory() -> Memory:
    m = Memory()
    m.record(incident_id="I1", text="portfolio balances stale, sync errors spiking", when=WHEN,
             services=["aa-sync"], report=_report("aa-sync", "db_pool_exhaustion"), topology=TOPO)  # fmt: skip
    m.record(incident_id="I2", text="orders fail with timeouts at the broker", when=WHEN,
             services=["order-router", "broker-gateway"], report=_report("broker-gateway", "timeout_config"), topology=TOPO)  # fmt: skip
    return m


def test_the_most_relevant_past_incident_comes_back_first() -> None:  # covers: R4
    hints = _memory().similar("balances look stale and sync is failing", ["aa-sync"], k=2)
    assert [h.id for h in hints][0] == "I1" and hints[0].source == "memory"
    assert "db_pool_exhaustion" in hints[0].root_cause and hints[0].fix == "roll back"


def test_unrelated_incidents_are_not_returned() -> None:  # covers: R4
    assert _memory().similar("completely different words here", ["web-app"]) == []
    assert Memory().similar("anything", ["aa-sync"]) == []


def test_neighbours_in_the_call_graph_count_but_less_than_a_direct_match() -> None:  # covers: R4
    m = _memory()
    direct = m.similar("slow", ["aa-sync"])
    near = m.similar("slow", ["postgres"])  # aa-sync CALLS postgres
    assert [h.id for h in near] == ["I1"] and [h.id for h in direct] == ["I1"]
    assert Memory().similar("slow", ["postgres"]) == []


def test_provenance_is_always_spelled_out() -> None:  # covers: R12
    m = _memory()
    assert "agent-concluded, UNCONFIRMED" in m.similar("sync errors", ["aa-sync"])[0].root_cause
    m.confirm("I1", True)
    assert "[CONFIRMED by on-call]" in m.similar("sync errors", ["aa-sync"])[0].root_cause
    m.confirm("I1", False, actual="a leaked connection in the batch job")
    rejected = m.similar("sync errors", ["aa-sync"])[0].root_cause
    assert "REJECTED by on-call" in rejected and "leaked connection" in rejected
    m.record(incident_id="I3", text="sync errors again", when=WHEN, services=["aa-sync"],
             report=_report("aa-sync", "x", status="INCONCLUSIVE", conf=0.2), topology=TOPO)  # fmt: skip
    assert any(
        "previously INCONCLUSIVE" in h.root_cause
        for h in m.similar("sync errors again", ["aa-sync"], k=5)
    )


def test_a_confirmed_incident_outranks_an_unconfirmed_one_with_equal_similarity() -> (
    None
):  # covers: R12
    m = Memory()
    for i in ("A", "B"):
        m.record(
            incident_id=i,
            text="pool exhausted sync",
            when=WHEN,
            services=["aa-sync"],
            report=_report("aa-sync", "p"),
            topology=TOPO,
        )
    m.confirm("B", True)
    assert [h.id for h in m.similar("pool exhausted sync", ["aa-sync"], k=2)] == ["B", "A"]


def test_base_rates_count_only_confirmed_causes() -> None:  # covers: R12
    m = _memory()
    assert not m.priors("aa-sync")
    m.confirm("I1", True)
    assert m.priors("aa-sync") == {"db_pool_exhaustion": 1}
    m.confirm("I1", False)
    assert not m.priors("aa-sync")


def test_the_current_incident_can_be_excluded_and_k_is_respected() -> None:  # covers: R17
    m = _memory()
    assert m.similar("sync errors stale balances", ["aa-sync"], exclude={"I1"}) == []
    for i in range(5):
        m.record(
            incident_id=f"X{i}",
            text="sync errors stale",
            when=WHEN,
            services=["aa-sync"],
            report=_report("aa-sync", "p"),
            topology=TOPO,
        )
    assert len(m.similar("sync errors stale", ["aa-sync"], k=3)) == 3


def test_stored_text_is_scrubbed_and_survives_a_restart(tmp_path: Path) -> None:  # covers: R5
    path = tmp_path / "memory.db"
    m = Memory(path)
    m.record(incident_id="S", text="auth failed for ops@corp.com token=abc123secret", when=WHEN,
             services=["aa-sync"], report=_report("aa-sync", "x"), topology=TOPO)  # fmt: skip
    again = Memory(path)
    assert len(again) == 1
    hint = again.similar("auth failed", ["aa-sync"])[0]
    assert "ops@corp.com" not in hint.summary and "abc123secret" not in hint.summary


async def test_memory_flows_through_an_investigation_and_into_the_next() -> None:  # covers: R4, R12
    m = Memory()
    first = Store.load(SCEN / "s01_bad_deploy")
    out = await investigate(first, LlmFactory("fake", script=Team()), memory=m, incident_id="first")
    assert (
        len(m) == 1 and out.report.status == "ANSWER"
    )  # recorded as the agent's unconfirmed conclusion
    second = Store(
        Dataset.model_validate_json((SCEN / "s01_bad_deploy" / "data.json").read_text("utf-8"))
    )
    await investigate(second, LlmFactory("fake", script=Team()), memory=m, incident_id="second")
    mem_items = [h for h in second.data.history if h.source == "memory"]
    assert [h.id for h in mem_items] == ["first"]  # the earlier run is offered as a hint
    shown = await invoke(second, "search_incidents", {"query": "orders fail placing error"})
    assert (
        shown.ok
        and "first" in (shown.result_json or "")
        and "UNCONFIRMED" in (shown.result_json or "")
    )
    assert len(m) == 2
