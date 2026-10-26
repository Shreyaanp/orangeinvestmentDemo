import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "orch"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src" / "scripts"))
from build_catalog import build  # noqa: E402
from team import Team  # noqa: E402

from eval import kb  # noqa: E402
from incident.knowledge import load, matches, past_fix_actions, render  # noqa: E402
from incident.llm import LlmFactory  # noqa: E402
from incident.memory import Memory  # noqa: E402
from incident.messages import Action, PastIncident, RankedHypothesis, Report, RunStats  # noqa: E402
from incident.orchestrator import investigate  # noqa: E402
from incident.state import Board  # noqa: E402
from incident.tools.store import Store  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SCEN = ROOT / "scenarios"
WHEN = datetime(2026, 1, 1, tzinfo=UTC)


def _top(component: str = "order-router", cause: str = "bad_deploy") -> RankedHypothesis:
    return RankedHypothesis(
        rank=1, hypothesis_id="H1", statement="s", component=component, cause_type=cause,
        score=3.0, confidence=0.8, label="high", supporting=[], contradicting=[],
    )  # fmt: skip


def _past(confirmed: bool | None, component: str = "order-router", cause: str = "bad_deploy"):  # type: ignore[no-untyped-def]
    return PastIncident(
        id="INC-1", date="2026-01-01", summary="orders failing", status="ANSWER",
        component=component, cause_type=cause, statement="release broke validation",
        confirmed=confirmed, fix="rolled back order-router-00417",
    )  # fmt: skip


def _report(component: str, cause: str) -> Report:
    act = Action(
        text="roll back release", rationale="r", evidence_ids=["E-1"], priority="immediate"
    )
    return Report(
        status="ANSWER", status_reason="", summary="", hypotheses=[_top(component, cause)],
        facts=[], assumptions=[], unresolved=[], actions=[act], stats=RunStats(),
    )  # fmt: skip


def test_catalogue_is_built_from_the_base_world_and_repo() -> None:  # covers: R4
    v1 = build(SCEN / "world.json", None, "v1")
    router = next(s for s in v1.services if s.name == "order-router")
    assert "broker-gateway" in router.calls and "rps" in router.metrics
    assert any(q.name == "inbound-msgs" for q in v1.queues)
    app = build(SCEN / "app" / "world.json", SCEN / "app" / "repo", "app")
    assert {t.name for t in app.tables} >= {"holdings", "prices"}
    assert "user_id" in next(t for t in app.tables if t.name == "holdings").columns
    assert app.config["worker.reserved_concurrency"] == "6" and app.modules
    text = render(app)
    assert "table holdings(user_id, symbol, qty)" in text and "not evidence" in text


def test_committed_catalogues_match_the_builder() -> None:  # covers: R4
    assert load(SCEN / "catalog" / "v1.json") == build(
        SCEN / "world.json", None, "Orange-Invest-like stack (V1)"
    )


def test_catalogue_never_names_incident_only_metrics() -> None:  # covers: R4
    """Metrics that exist only while a fault runs would hint at the answer."""
    text = render(load(SCEN / "catalog" / "v1.json"))
    assert "duplicate_orders" not in text and "cache_staleness_s" not in text


def test_only_a_confirmed_lookalike_on_the_same_component_and_cause_gives_a_fix() -> (
    None
):  # covers: R4
    assert matches(_past(True), _top())
    assert not matches(_past(None), _top()) and not matches(_past(False), _top())
    assert not matches(_past(True, component="broker-gateway"), _top())
    assert not matches(_past(True, cause="db_pool_exhaustion"), _top())
    assert matches(_past(True, cause="deploy_regression"), _top())  # shares "deploy"


def test_a_history_fix_is_labelled_and_cites_a_history_assumption() -> None:  # covers: R4, R6
    b = Board(incident_text="x")
    b.past = [_past(True), _past(False)]
    (act,) = past_fix_actions(b, _top())
    assert act.source == "history" and act.text.startswith("[from history: INC-1]")
    ev = b.evidence[act.evidence_ids[0]]
    assert ev.kind == "ASSUMPTION" and "history" in ev.flags and ev.reliability < 1


async def test_memory_reaches_the_prompts_and_the_report_without_changing_the_verdict() -> (
    None
):  # covers: R4, R6
    seen: list[str] = []

    class Spy(Team):
        def __call__(self, key: str, n: int, system: str, prompt: str) -> str:
            seen.append(prompt)
            return super().__call__(key, n, system, prompt)

    m = Memory()
    m.record(incident_id="INC-9", text=Store.load(SCEN / "s01_bad_deploy").data.incident.text,
             when=WHEN, services=["order-router"], report=_report("order-router", "test_cause"))  # fmt: skip
    m.confirm("INC-9", True, fix="rolled back the bad release")
    plain = await investigate(
        Store.load(SCEN / "s01_bad_deploy"), LlmFactory("fake", script=Team())
    )
    cat = load(SCEN / "catalog" / "v1.json")
    out = await investigate(
        Store.load(SCEN / "s01_bad_deploy"), LlmFactory("fake", script=Spy()), memory=m,
        catalogue=cat,
    )  # fmt: skip
    assert any("SYSTEM CATALOGUE" in p and "INC-9" in p for p in seen)
    hist = [a for a in out.report.actions if a.source == "history"]
    assert len(hist) == 1 and "rolled back the bad release" in hist[0].text
    assert out.report.status == plain.report.status
    assert out.report.hypotheses[0].confidence == plain.report.hypotheses[0].confidence


def test_kb_modes_hold_what_they_claim() -> None:  # covers: R4
    names = sorted(d.name for d in SCEN.iterdir() if (d / "truth.json").exists())
    q = "s01_bad_deploy"
    loo = kb.build(q, "loo", names)
    rec = kb.build(q, "recurrence", names)
    mis = kb.build(q, "misleading", names)
    text = Store.load(SCEN / q).data.incident.text
    ids = lambda m: {p.id for p in m.similar_past(text, ["order-router"], k=50)}  # noqa: E731
    assert q not in ids(loo) and kb.PREV not in ids(loo)
    assert kb.PREV in ids(rec)
    look = next(p for p in mis.similar_past(text, ["order-router"], k=50) if p.id == kb.LOOKALIKE)
    assert look.confirmed is True and look.component != "order-router"
