import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from eval import memory_eval
from incident.memory import Memory
from incident.messages import Action, RankedHypothesis, Report, RunStats
from incident.models import Dataset
from incident.retrieval import FakeEmbedder, FakeReranker, Retriever, bm25, build, rrf
from incident.tools import history

SCEN = Path(__file__).resolve().parents[2] / "scenarios"
WHEN = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
DOCS = [
    "aa-sync database connection pool exhausted, sync slow",
    "broker gateway timeout lowered by a config change",
    "redis cache stampede after hot key expiry",
]


def _data() -> Dataset:
    return Dataset.model_validate_json(
        (SCEN / "s08_stale_history" / "data.json").read_text("utf-8")
    )


def _report(component: str, cause: str) -> Report:
    top = RankedHypothesis(
        rank=1, hypothesis_id="H1", statement=f"{component} {cause}", component=component,
        cause_type=cause, score=3.0, confidence=0.8, label="high", supporting=[], contradicting=[],
    )  # fmt: skip
    act = Action(text="roll back", rationale="r", evidence_ids=["E-001"], priority="immediate")
    return Report(
        status="ANSWER", status_reason="", summary="", hypotheses=[top], facts=[], assumptions=[],
        unresolved=[], actions=[act], stats=RunStats(),
    )  # fmt: skip


def test_bm25_and_rank_fusion_prefer_the_matching_doc() -> None:  # covers: R4
    s = bm25("connection pool exhausted", DOCS)
    assert s[0] > 0 and s[1] == s[2] == 0
    fused = rrf([[3.0, 1.0, 0.0], [0.0, 2.0, 1.0]])
    assert fused[1] > fused[0] > fused[2] > 0 and rrf([[0.0, 0.0]]) == [0.0, 0.0]


def test_fake_embedder_is_deterministic_and_normalised() -> None:  # covers: R4
    a, b = FakeEmbedder().embed(["cpu throttled"]), FakeEmbedder().embed(["cpu throttled"])
    assert a == b and abs(sum(x * x for x in a[0]) - 1.0) < 1e-9
    assert FakeReranker().score("pool exhausted", DOCS)[0] == 1.0


def test_hybrid_ranks_relevant_first_and_drops_unrelated() -> None:  # covers: R4
    r = Retriever(FakeEmbedder(), FakeReranker())
    assert [i for i, _ in r.rank("the connection pool is exhausted", DOCS)][0] == 0
    assert r.rank("wholly different vocabulary entirely", DOCS) == []
    assert r.rank("anything", []) == []
    assert all(0.0 <= rel <= 1.0 for _, rel in r.rank("cache stampede", DOCS))


def test_retrieval_is_off_unless_opted_in(monkeypatch: pytest.MonkeyPatch) -> None:  # covers: R4
    monkeypatch.delenv("RETRIEVAL", raising=False)
    assert build() is None and build("keyword") is None and Memory().retriever is None
    monkeypatch.setenv("RETRIEVAL", "fake")
    assert isinstance(build(), Retriever) and isinstance(Memory().retriever, Retriever)
    with pytest.raises(ValueError, match="RETRIEVAL"):
        build("vectors")


def test_search_incidents_default_output_is_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # covers: R4
    monkeypatch.delenv("RETRIEVAL", raising=False)
    data, q = _data(), history.Query(query="cache stampede redis ttl expiry", limit=3)
    want = history._tokens(q.query)
    overlap = [
        len(want & history._tokens(f"{h.summary} {h.root_cause} {h.fix}")) for h in data.history
    ]
    expect = [
        h.id for n, h in sorted(zip(overlap, data.history, strict=True), key=lambda x: -x[0]) if n
    ][:3]
    assert [h.id for h in history.run(data, q).items] == expect
    monkeypatch.setenv("RETRIEVAL", "fake")
    hybrid = history.run(data, q)
    assert hybrid.items and {"INC-0412", "INC-0440"} & {h.id for h in hybrid.items[:2]}


def test_memory_with_hybrid_retrieval_keeps_provenance_labels() -> None:  # covers: R12
    m = Memory(retrieval="fake")
    m.record(incident_id="I1", text="portfolio balances stale, sync errors spiking", when=WHEN,
             services=["aa-sync"], report=_report("aa-sync", "db_pool_exhaustion"))  # fmt: skip
    m.record(incident_id="I2", text="orders fail with timeouts at the broker", when=WHEN,
             services=["broker-gateway"], report=_report("broker-gateway", "timeout"))  # fmt: skip
    hints = m.similar("balances look stale and syncing is failing", ["aa-sync"])
    assert hints[0].id == "I1" and "UNCONFIRMED" in hints[0].root_cause
    assert m.similar("completely different words here", ["web-app"]) == []


def test_memory_eval_runs_offline_and_misleading_memory_stays_a_hint() -> None:  # covers: R12, R16
    cases = memory_eval.load_cases()[:5]
    for mode in ("keyword", "fake"):
        assert memory_eval.recall_metrics(cases, mode, "shift")["recall@1"] == 1.0
        mis = memory_eval.misleading(cases, mode)
        assert mis["all_hints_labelled"] == mis["hint_graded_as_history"] == 1.0
        assert mis["true_first_after_feedback"] == mis["lookalike_marked_rejected"] == 1.0
    assert json.dumps(memory_eval.recall_metrics(cases, "keyword", "postmortem"))


def test_fastembed_hybrid_end_to_end() -> None:  # opt-in: needs fastembed and a model download
    pytest.importorskip("fastembed")
    r = build("hybrid")
    assert r is not None
    assert [i for i, _ in r.rank("database connections are all in use", DOCS)][0] == 0
