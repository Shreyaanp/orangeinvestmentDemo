import json
from datetime import timedelta
from pathlib import Path

import pytest

from incident.models import Dataset
from incident.sim.truth import Truth
from incident.tools import digest
from incident.tools.guard import invoke
from incident.tools.registry import ALL_TOOLS, TOOLS
from incident.tools.schemas import InvalidInput
from incident.tools.store import Store

SCEN = Path(__file__).resolve().parents[2] / "scenarios"
DIRS = sorted(d for d in SCEN.iterdir() if (d / "truth.json").exists())


def _data(name: str) -> Dataset:
    return Dataset.model_validate_json((SCEN / name / "data.json").read_text("utf-8"))


def _minutes(d: Dataset, ts) -> int:  # type: ignore[no-untyped-def]
    return int((ts - d.start).total_seconds() // 60)


def test_the_culprit_is_the_first_to_deviate_in_a_clean_case() -> None:  # covers: R4
    d = _data("s01_bad_deploy")
    items = digest.anomalies(d, digest.AnomalyQuery()).items
    assert items[0].service == "order-router" and items[0].metric == "err_rate"
    assert 70 <= _minutes(d, items[0].onset) <= 73 and items[0].direction == "up"
    assert items[0].peak > 0.25 > items[0].baseline


def test_noise_on_tiny_or_rounded_values_is_not_an_incident() -> None:  # covers: R4
    d = _data("s01_bad_deploy")
    flagged = {
        (a.service, a.metric) for a in digest.anomalies(d, digest.AnomalyQuery(top_n=40)).items
    }
    assert ("redis-cache", "err_rate") not in flagged and ("postgres", "err_rate") not in flagged
    assert ("orchestrator", "rps") not in flagged


def test_a_single_spike_is_not_sustained() -> None:  # covers: R4
    d = _data("s01_bad_deploy")
    metrics = {s: {m: list(v) for m, v in ms.items()} for s, ms in d.metrics.items()}
    metrics["auth-kyc"]["latency_ms"][80] = 99999.0  # one bad minute
    flagged = digest.anomalies(
        d.model_copy(update={"metrics": metrics}), digest.AnomalyQuery(top_n=40)
    )
    assert ("auth-kyc", "latency_ms") not in {(a.service, a.metric) for a in flagged.items}


def test_missing_data_is_skipped_not_treated_as_zero() -> None:  # covers: R4
    d = _data("s01_bad_deploy")
    metrics = {s: {m: list(v) for m, v in ms.items()} for s, ms in d.metrics.items()}
    metrics["order-router"]["err_rate"] = [None] * d.minutes
    items = digest.anomalies(d.model_copy(update={"metrics": metrics}), digest.AnomalyQuery()).items
    assert ("order-router", "err_rate") not in {(a.service, a.metric) for a in items}


def test_new_log_patterns_come_first_with_normalised_numbers() -> None:  # covers: R4
    d = _data("s09_metrics_down")
    res = digest.patterns(d, digest.PatternQuery(top_n=10))
    new = [p for p in res.items if p.in_baseline == 0]
    assert new and res.items[0].in_baseline == 0
    assert any("ttl expiry burst" in p.template and "#" in p.template for p in new)  # 8000 -> #
    assert all(p.first_seen <= p.last_seen and p.count >= 1 for p in res.items)


def test_digest_inputs_are_validated() -> None:  # covers: R5
    d = _data("s01_bad_deploy")
    with pytest.raises(InvalidInput):
        digest.anomalies(d, digest.AnomalyQuery(service="nope"))
    with pytest.raises(InvalidInput):
        digest.patterns(d, digest.PatternQuery(service="nope"))
    with pytest.raises(InvalidInput):
        digest.anomalies(d, digest.AnomalyQuery(start=d.start, end=d.start + timedelta(minutes=3)))


def test_the_digest_is_orders_of_magnitude_smaller_than_the_raw_data() -> None:  # covers: R4
    d = _data("s01_bad_deploy")
    small = len(digest.anomalies(d, digest.AnomalyQuery()).model_dump_json())
    raw = len(d.model_dump_json())
    assert small * 100 < raw


def test_detection_quality_across_all_scenarios() -> None:  # covers: R16
    """No model involved: how often is the true culprit among the first services to deviate?"""
    top1 = top3 = 0
    for d in DIRS:
        data = _data(d.name)
        truth = Truth.model_validate_json((d / "truth.json").read_text("utf-8"))
        comps = {f.component for f in truth.faults}
        order: list[str] = []
        for a in digest.anomalies(data, digest.AnomalyQuery(top_n=40)).items:
            if a.service not in order:
                order.append(a.service)
        top1 += bool(order and order[0] in comps)
        top3 += bool(comps & set(order[:3]))
    assert top1 >= 11 and top3 >= 15, (top1, top3, len(DIRS))  # measured: 13 and 17 of 19


async def test_digest_tools_run_through_the_guard_but_are_not_in_the_default_toolset() -> (
    None
):  # covers: R4
    assert "get_anomalies" not in TOOLS and "get_log_patterns" not in TOOLS  # the evaluated default
    assert {"get_anomalies", "get_log_patterns"} <= set(ALL_TOOLS)
    store = Store.load(SCEN / "s01_bad_deploy")
    out = await invoke(store, "get_anomalies", {"top_n": 3, "z": None})
    items = json.loads(out.result_json or "{}")["items"]
    assert out.ok and 1 <= len(items) <= 3
    bad = await invoke(store, "get_log_patterns", {"service": "nope"})
    assert not bad.ok and bad.error and bad.error.kind == "invalid_input"
