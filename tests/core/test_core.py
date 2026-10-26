import json
from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st

from incident.grounding import check_evidence, claim_kind, clean_claims
from incident.messages import Claim, EvidenceDraft, HypothesisDraft, ReasoningResult
from incident.scoring import rank, verdict
from incident.state import Board, Limits
from incident.tools.guard import invoke
from incident.tools.store import Store

SCEN = Path(__file__).resolve().parents[2] / "scenarios"


def _board(**limits: float) -> Board:
    return Board(incident_text="x", limits=Limits(**limits))  # type: ignore[arg-type]


def _facts(b: Board, reliabilities: list[float]) -> list[str]:
    ids = []
    for r in reliabilities:
        d = EvidenceDraft(kind="FACT", claim="c", excerpt="e", source_call_id="tc-0001")
        ids.append(b.add_evidence(d, "observability", r, []).id)
    return ids


def _hyp(b: Board, support: list[str], contra: list[str] | None = None, **kw: object) -> str:
    draft = HypothesisDraft(
        statement="s", supporting=support, **{"component": "svc", "cause_type": "t", **kw},
        contradicting=contra or [],  # type: ignore[arg-type]
    )  # fmt: skip
    return b.upsert_hypotheses(ReasoningResult(hypotheses=[draft]))[0].id


# ---------- scoring ----------


@given(st.lists(st.floats(0.1, 1.0), min_size=1, max_size=8), st.floats(0.1, 1.0))
def test_more_support_never_lowers_confidence(
    rels: list[float], extra: float
) -> None:  # covers: R11
    b = _board()
    ids = _facts(b, rels)
    h = _hyp(b, ids)
    before = rank(b)[0].confidence
    more = _facts(b, [extra])
    _hyp(b, ids + more, id=h)  # type: ignore[arg-type]
    assert rank(b)[0].confidence >= before


@given(st.lists(st.floats(0.1, 1.0), min_size=1, max_size=6), st.floats(0.1, 1.0))
def test_contradiction_never_raises_confidence(
    rels: list[float], contra: float
) -> None:  # covers: R11
    b = _board()
    ids = _facts(b, rels)
    h = _hyp(b, ids)
    before = rank(b)[0].confidence
    _hyp(b, ids, _facts(b, [contra]), id=h)  # type: ignore[arg-type]
    assert rank(b)[0].confidence <= before


def test_open_gaps_cap_confidence() -> None:  # covers: R13
    b = _board()
    _hyp(b, _facts(b, [1.0] * 40))
    assert rank(b)[0].confidence == 0.9
    for i in range(3):
        b.add_gap(f"gap {i}")
    assert rank(b)[0].confidence == 0.6
    for i in range(10):
        b.add_gap(f"more {i}")
    assert rank(b)[0].confidence == 0.5  # floor


def test_verdict_inconclusive_without_support_or_with_close_rivals() -> None:  # covers: R13
    b = _board()
    assert verdict(b).status == "INCONCLUSIVE"
    a = _hyp(b, _facts(b, [1.0] * 4))
    assert verdict(b).status == "ANSWER"
    _hyp(b, _facts(b, [1.0] * 4))  # an equally supported rival
    v = verdict(b)
    assert v.status == "INCONCLUSIVE" and "rivals" in v.reason
    assert a in {r.hypothesis.id for r in v.ranked}


def test_independent_causes_do_not_compete() -> None:  # covers: R11
    b = _board()
    first = _hyp(b, _facts(b, [1.0] * 5))
    second = _hyp(b, _facts(b, [1.0] * 5), compatible_with=[first])
    assert second and verdict(b).status == "ANSWER"


def test_near_synonyms_on_one_component_do_not_block_an_answer() -> None:  # covers: R11, R13
    b = _board()
    _hyp(b, _facts(b, [1.0] * 5), component="gw", cause_type="dependency_degradation")
    _hyp(b, _facts(b, [1.0] * 5), component="gw", cause_type="upstream_dependency_slowdown")
    assert verdict(b).status == "ANSWER"
    _hyp(b, _facts(b, [1.0] * 5), component="gw", cause_type="rate_limit_exhaustion")
    assert verdict(b).status == "INCONCLUSIVE"  # a different mechanism still competes
    c = _board()
    _hyp(c, _facts(c, [1.0] * 5), component="gw", cause_type="dependency_degradation")
    _hyp(c, _facts(c, [1.0] * 5), component="router", cause_type="dependency_retry")
    assert verdict(c).status == "INCONCLUSIVE"  # a shared word elsewhere is not a synonym


def test_weak_top_is_inconclusive() -> None:  # covers: R13
    b = _board()
    _hyp(b, _facts(b, [0.3]))
    v = verdict(b)
    assert v.status == "INCONCLUSIVE" and "below" in v.reason


# ---------- state ----------


def test_ids_unknown_evidence_and_rejection() -> None:  # covers: R7
    b = _board()
    ids = _facts(b, [1.0, 1.0])
    assert ids == ["E-001", "E-002"]
    h = _hyp(b, ids + ["E-999"])
    assert b.hypotheses[h].supporting == ids and any("E-999" in r for r in b.rejected)
    b.upsert_hypotheses(ReasoningResult(hypotheses=[], rejected=[h]))
    assert b.hypotheses[h].status == "rejected" and rank(b) == []


def test_task_dependencies_and_blocking() -> None:  # covers: R7
    b = _board()
    t1 = b.add_task("observability", "a")
    t2 = b.add_task("dependency", "b", depends_on=[t1.id])
    assert [t.id for t in b.ready_tasks()] == [t1.id]
    b.tasks[t1.id].status = "done"
    assert [t.id for t in b.ready_tasks()] == [t2.id]
    b.tasks[t1.id].status = "failed"
    assert [t.id for t in b.blocked_tasks()] == [t2.id] and b.ready_tasks() == []


def test_budget_limits_are_enforced() -> None:  # covers: R9
    b = _board(max_tool_calls=2, max_tokens=100, max_seconds=5)
    assert b.budget_exceeded() is None
    b.usage.tool_calls = 2
    assert "tool-call" in (b.budget_exceeded() or "")
    b.usage.tool_calls, b.usage.tokens_in, b.usage.tokens_out = 0, 60, 40
    assert "token" in (b.budget_exceeded() or "")
    b.usage.tokens_in = b.usage.tokens_out = 0
    b.elapsed_s = 5
    assert "time" in (b.budget_exceeded() or "")


def test_board_survives_checkpoint_roundtrip() -> None:  # covers: R10
    b = _board()
    _hyp(b, _facts(b, [1.0, 0.6]))
    b.add_task("observability", "look")
    b.add_gap("tool timed out")
    assert Board.model_validate_json(b.model_dump_json()) == b


# ---------- grounding ----------


async def _store_with_logs() -> tuple[Store, str, str]:
    store = Store.load(SCEN / "s01_bad_deploy")
    window = {"start": "2026-03-12T13:10:00Z", "end": "2026-03-12T13:11:00Z"}
    out = await invoke(store, "query_logs", {"service": "order-router", "level": "ERROR", **window})
    assert out.result_json and not out.truncated
    msg = json.loads(out.result_json)["items"][0]["msg"]
    return store, out.call_id, msg


async def test_truncated_results_lower_reliability() -> None:  # covers: R12
    store = Store.load(SCEN / "s01_bad_deploy")
    args = {"service": "order-router", "level": "ERROR", "limit": 3}
    out = await invoke(store, "query_logs", args)
    msg = json.loads(out.result_json or "{}")["items"][0]["msg"]
    draft = EvidenceDraft(kind="FACT", claim="c", excerpt=msg, source_call_id=out.call_id)
    g = check_evidence(draft, store.results)
    assert g.ok and g.flags == ["truncated"] and g.reliability == 0.8


async def test_verbatim_excerpt_is_accepted_and_paraphrase_of_words_too() -> None:  # covers: R12
    store, call, msg = await _store_with_logs()
    ok = check_evidence(
        EvidenceDraft(kind="FACT", claim="c", excerpt=msg, source_call_id=call), store.results
    )
    assert ok.ok and ok.reliability == 1.0
    loose = check_evidence(
        EvidenceDraft(
            kind="FACT",
            claim="c",
            excerpt="unhandled exception in place_order KeyError",
            source_call_id=call,
        ),
        store.results,
    )
    assert loose.ok


async def test_invented_evidence_is_rejected() -> None:  # covers: R12
    store, call, msg = await _store_with_logs()

    def verdict_of(**kw: object) -> bool:
        d = EvidenceDraft(kind="FACT", claim="c", **kw)  # type: ignore[arg-type]
        return check_evidence(d, store.results).ok

    assert not verdict_of(excerpt="connection pool exhausted: 100/100", source_call_id=call)
    assert not verdict_of(
        excerpt=msg + " after 9999 retries", source_call_id=call
    )  # invented number
    assert not verdict_of(excerpt=msg, source_call_id="tc-0099")
    assert not verdict_of(excerpt=msg, source_call_id=None)
    assert not verdict_of(excerpt="", source_call_id=call)


async def test_partial_and_history_results_are_less_reliable() -> None:  # covers: R12
    data = Store.load(SCEN / "s09_metrics_down").data
    store = Store(data)
    out = await invoke(store, "query_metrics", {"service": "redis-cache"}, retries=3, backoff_s=0)
    assert out.partial
    stat = json.loads(out.result_json or "{}")["items"][0]["metric"]
    g = check_evidence(
        EvidenceDraft(kind="FACT", claim="c", excerpt=stat, source_call_id=out.call_id),
        store.results,
    )
    assert g.ok and g.flags == ["partial"] and g.reliability == 0.6
    hist = await invoke(store, "search_incidents", {"query": "cache stampede redis"})
    h = check_evidence(
        EvidenceDraft(
            kind="FACT",
            claim="c",
            excerpt="Cache stampede on hot context",
            source_call_id=hist.call_id,
        ),
        store.results,
    )
    assert h.ok and h.flags == ["history"] and h.reliability == 0.5


def test_assumptions_need_no_source_but_are_low_reliability() -> None:  # covers: R12
    g = check_evidence(EvidenceDraft(kind="ASSUMPTION", claim="maybe a leak"), {})
    assert g.ok and g.reliability == 0.3 and g.flags == ["assumption"]


def test_claims_must_cite_existing_evidence_and_facts_stay_separate() -> None:  # covers: R12
    b = _board()
    fact, assumption = (
        b.add_evidence(
            EvidenceDraft(kind="FACT", claim="f", excerpt="e", source_call_id="x"),
            "dependency",
            1.0,
            [],
        ),
        b.add_evidence(
            EvidenceDraft(kind="ASSUMPTION", claim="a"), "reasoning", 0.3, ["assumption"]
        ),
    )
    claims = [
        Claim(text="ok", evidence_ids=[fact.id]),
        Claim(text="uncited", evidence_ids=[]),
        Claim(text="ghost", evidence_ids=["E-404"]),
        Claim(text="mixed", evidence_ids=[fact.id, assumption.id]),
    ]
    kept, dropped = clean_claims(claims, b.evidence)
    assert [c.text for c in kept] == ["ok", "mixed"] and dropped == 2
    assert (
        claim_kind(kept[0], b.evidence) == "FACT"
        and claim_kind(kept[1], b.evidence) == "ASSUMPTION"
    )


def test_llm_output_models_treat_null_as_not_provided() -> None:  # covers: R2
    d = EvidenceDraft.model_validate_json(
        '{"kind":"ASSUMPTION","claim":"x","excerpt":null,"source_call_id":null,"ts":null}'
    )
    assert d.excerpt == "" and d.source_call_id is None
    h = HypothesisDraft.model_validate_json(
        '{"statement":"s","component":"c","cause_type":"t","supporting":["E-001"],"contradicting":null}'
    )
    assert h.contradicting == []


def test_llm_answers_ignore_unknown_fields_but_tool_arguments_do_not() -> None:  # covers: R2, R5
    h = HypothesisDraft.model_validate_json(
        '{"statement":"s","component":"c","cause_type":"t","supporting":[],"ref_note":"extra"}'
    )
    assert h.component == "c" and not hasattr(h, "ref_note")
    from incident.tools.logs import Query

    try:
        Query.model_validate({"service": "x", "types": ["deploy"]})
    except ValueError as e:
        assert "types" in str(e)
    else:
        raise AssertionError("an unknown tool argument must be rejected")


def test_evidence_every_hypothesis_explains_is_shared_credit() -> None:  # covers: R11
    b = _board()
    common = _facts(b, [1.0] * 4)  # e.g. "latency stepped up": every hypothesis cites it
    a = _hyp(b, common + _facts(b, [1.0]))
    c = _hyp(b, common + _facts(b, [1.0]))
    by_id = {r.hypothesis.id: r for r in rank(b)}
    assert by_id[a].support == by_id[c].support == 4 * 0.5 + 1.0  # shared facts split, unique kept
    solo = _board()
    only = _hyp(solo, _facts(solo, [1.0] * 4))
    assert {r.hypothesis.id: r for r in rank(solo)}[
        only
    ].support == 4.0  # nobody shares: full credit


def test_a_leader_that_is_substantially_contradicted_is_not_an_answer() -> None:  # covers: R13
    b = _board()
    # strong support, but heavy contradiction; a weak rival makes the margin look comfortable
    lead = _hyp(b, _facts(b, [1.0] * 40), _facts(b, [1.0] * 30 + [0.5]))  # 30.5 > 0.75 * 40
    _hyp(b, _facts(b, [0.3]))
    v = verdict(b)
    assert v.ranked[0].hypothesis.id == lead and v.margin >= b.limits.margin
    assert v.status == "INCONCLUSIVE" and "contradicted" in v.reason


def test_a_well_supported_uncontradicted_leader_is_still_an_answer() -> None:  # covers: R11
    b = _board()
    _hyp(b, _facts(b, [1.0] * 6), _facts(b, [0.5]))
    assert verdict(b).status == "ANSWER"


async def test_a_search_that_found_nothing_is_weak_evidence() -> None:  # covers: R12
    store = Store.load(SCEN / "s01_bad_deploy")
    out = await invoke(store, "query_logs", {"contains": "no-such-text-anywhere"})
    assert out.ok and json.loads(out.result_json or "{}")["items"] == []
    draft = EvidenceDraft(
        kind="FACT", claim="no such lines", excerpt="total 0 items", source_call_id=out.call_id
    )
    g = check_evidence(draft, store.results)
    assert g.ok and g.flags == ["empty"] and g.reliability == 0.4


def test_uncorroborated_facts_cost_less_than_refuting_ones() -> None:  # covers: R11
    def conf(**kw: list[str]) -> float:
        b = _board()
        sup, other = _facts(b, [1.0] * 5), _facts(b, [1.0] * 4)
        h = _hyp(
            b,
            sup,
            other if kw.get("refute") else [],
            uncorroborated=other if kw.get("weak") else [],
        )
        return next(r.confidence for r in verdict(b).ranked if r.hypothesis.id == h)

    clean, weak, refuted = conf(), conf(weak=["x"]), conf(refute=["x"])
    assert refuted < weak < clean


def test_a_fact_listed_as_both_is_counted_once_as_refuting() -> None:  # covers: R11
    b = _board()
    ids = _facts(b, [1.0] * 3)
    both = _hyp(b, _facts(b, [1.0] * 5), ids, uncorroborated=ids)
    only = _hyp(b, _facts(b, [1.0] * 5), ids)
    ranked = {r.hypothesis.id: r for r in verdict(b).ranked}
    assert ranked[both].contra == ranked[only].contra


def test_unknown_uncorroborated_ids_are_dropped_and_recorded() -> None:  # covers: R5
    b = _board()
    h = _hyp(b, _facts(b, [1.0]), uncorroborated=["E-999"])
    assert b.hypotheses[h].uncorroborated == [] and any("E-999" in r for r in b.rejected)
