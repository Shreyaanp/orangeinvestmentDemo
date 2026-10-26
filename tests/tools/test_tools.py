import json
from pathlib import Path

import pytest

from incident.models import Dataset, ToolFault, ToolName
from incident.tools.guard import invoke
from incident.tools.registry import ALL_TOOLS
from incident.tools.store import Store

SCEN = Path(__file__).resolve().parents[2] / "scenarios"
BASE = Dataset.model_validate_json((SCEN / "s01_bad_deploy" / "data.json").read_text("utf-8"))
CALLS: dict[ToolName, dict] = {
    "query_logs": {"service": "order-router", "level": "ERROR"},
    "query_metrics": {"service": "order-router"},
    "get_changes": {"kinds": ["deploy", "config"]},
    "get_dependencies": {"service": "order-router"},
    "search_incidents": {"query": "order errors release"},
}


def _store(*faults: ToolFault) -> Store:
    return Store(BASE.model_copy(update={"tool_faults": list(faults)}))


def _items(out) -> list[dict]:  # type: ignore[no-untyped-def]
    return json.loads(out.result_json)["items"]


async def test_logs_filter_and_limit() -> None:  # covers: R4
    out = await invoke(_store(), "query_logs", {"service": "order-router", "level": "ERROR"})
    assert out.ok and all(
        i["service"] == "order-router" and i["level"] == "ERROR" for i in _items(out)
    )
    small = await invoke(_store(), "query_logs", {"service": "order-router", "limit": 5})
    body = json.loads(small.result_json)
    assert len(body["items"]) == 5 and body["truncated"] and body["total"] > 5 and small.truncated


async def test_level_is_minimum_severity() -> None:  # covers: R4
    out = await invoke(_store(), "query_logs", {"level": "WARN", "limit": 200})
    assert {i["level"] for i in _items(out)} <= {"WARN", "ERROR"}


async def test_invalid_input_is_a_typed_error_not_a_crash() -> None:  # covers: R5
    for tool, args in [
        ("query_logs", {"service": "nope"}),
        ("query_logs", {"limit": 0}),
        ("query_logs", {"surprise": 1}),
        ("query_metrics", {"service": "order-router", "metric": "nope"}),
        ("get_dependencies", {"service": "nope"}),
    ]:
        out = await invoke(_store(), tool, args)  # type: ignore[arg-type]
        assert not out.ok and out.error and out.error.kind == "invalid_input"
        assert not out.error.retryable and out.attempts <= 1


async def test_metrics_summary_vs_points() -> None:  # covers: R4
    summary = await invoke(_store(), "query_metrics", {"service": "order-router"})
    assert len(_items(summary)) == 3 and all(i["points"] is None for i in _items(summary))
    one = await invoke(_store(), "query_metrics", {"service": "order-router", "metric": "err_rate"})
    pts = _items(one)[0]["points"]
    assert len(pts) == 24 and _items(one)[0]["stats"]["max"] > 0.2  # the injected bug is visible
    window = await invoke(
        _store(),
        "query_metrics",
        {
            "service": "order-router",
            "metric": "err_rate",
            "start": "2026-03-12T13:20:00",
            "step_min": 1,
        },
    )
    assert len(_items(window)[0]["points"]) == 40  # naive datetimes are read as UTC


async def test_changes_default_to_deploys_only() -> None:  # covers: R4
    s03 = Dataset.model_validate_json(
        (SCEN / "s03_config_not_deploy" / "data.json").read_text("utf-8")
    )
    default = await invoke(Store(s03), "get_changes", {})
    assert all(c["kind"] == "deploy" for c in _items(default))
    cfg = await invoke(Store(s03), "get_changes", {"kinds": ["config"]})
    assert [c["ref"] for c in _items(cfg)] == ["cfg-broker-timeout-ms"]


async def test_dependencies_for_service_and_queue() -> None:  # covers: R4
    svc = await invoke(_store(), "get_dependencies", {"service": "aa-sync"})
    dirs = {(i["direction"], i["name"]) for i in _items(svc)}
    assert ("publishes_to", "portfolio-updates") in dirs and ("calls", "postgres") in dirs
    q = await invoke(_store(), "get_dependencies", {"service": "portfolio-updates"})
    assert {("published_by", "aa-sync"), ("consumed_by", "portfolio-consumer")} <= {
        (i["direction"], i["name"]) for i in _items(q)
    }


async def test_incident_search_ranks_by_overlap() -> None:  # covers: R4
    out = await invoke(
        _store(), "search_incidents", {"query": "order placement errors after release"}
    )
    assert _items(out)[0]["id"] == "INC-0431"


@pytest.mark.parametrize("tool", list(CALLS))
@pytest.mark.parametrize("kind", ["timeout", "unavailable", "truncate", "partial"])
async def test_fault_matrix(tool: ToolName, kind: str) -> None:  # covers: R5
    fault = ToolFault(tool=tool, kind=kind, max_results=1)  # type: ignore[arg-type]
    out = await invoke(_store(fault), tool, CALLS[tool], retries=1, backoff_s=0)
    if kind in ("timeout", "unavailable"):
        assert not out.ok and out.error and out.error.kind == kind and out.attempts == 2
    else:
        assert out.ok and len(_items(out)) <= 1
        assert (out.truncated if kind == "truncate" else out.partial) or len(_items(out)) <= 1
    if kind == "partial":
        assert out.partial and json.loads(out.result_json)["total"] is None


async def test_retry_recovers_after_transient_faults() -> None:  # covers: R5, R9
    faults = [
        ToolFault(tool="query_metrics", kind="timeout", on_calls=[1, 2]),
        ToolFault(tool="query_metrics", kind="partial", on_calls=[3], max_results=2),
    ]
    store = _store(*faults)
    out = await invoke(store, "query_metrics", {"service": "order-router"}, retries=2, backoff_s=0)
    assert out.ok and out.attempts == 3 and out.partial and len(_items(out)) == 2
    assert store.attempts["query_metrics"] == 3


async def test_retries_are_bounded() -> None:  # covers: R9
    store = _store(ToolFault(tool="query_logs", kind="timeout"))
    out = await invoke(store, "query_logs", {}, retries=2, backoff_s=0)
    assert not out.ok and out.attempts == 3 and store.attempts["query_logs"] == 3


async def test_real_timeout_is_enforced(monkeypatch: pytest.MonkeyPatch) -> None:  # covers: R5
    import time

    spec = ALL_TOOLS["query_logs"]
    monkeypatch.setitem(
        ALL_TOOLS,
        "query_logs",
        type(spec)(spec.name, spec.description, spec.input, lambda d, q: time.sleep(0.3)),
    )  # type: ignore[arg-type,return-value]
    out = await invoke(_store(), "query_logs", {}, timeout_s=0.05, retries=0)
    assert not out.ok and out.error and out.error.kind == "timeout"


async def test_call_ids_unique_and_results_kept_for_grounding() -> None:  # covers: R12
    store = _store()
    a = await invoke(store, "query_logs", {"limit": 3})
    b = await invoke(store, "get_dependencies", {"service": "web-app"})
    assert a.call_id != b.call_id and store.results[a.call_id] == a.result_json
    assert store.calls == 2


async def test_fault_counters_are_per_store() -> None:  # covers: R5
    fault = ToolFault(tool="query_logs", kind="timeout", on_calls=[1])
    first = await invoke(_store(fault), "query_logs", {}, retries=0)
    second = await invoke(_store(fault), "query_logs", {}, retries=0)
    assert not first.ok and not second.ok  # a fresh run sees the same fault again
