"""Conformance: ingesting a scenario THROUGH the real wire protocols reproduces the scenario."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "orch"))
from team import Team  # noqa: E402

from incident.agents.tools import render  # noqa: E402
from incident.llm import LlmFactory  # noqa: E402
from incident.models import Dataset  # noqa: E402
from incident.orchestrator import investigate  # noqa: E402
from incident.tools.guard import invoke  # noqa: E402
from incident.tools.store import Store  # noqa: E402
from mockworld.apis import Faults  # noqa: E402
from mockworld.ingest import ingest_via_mock  # noqa: E402

SCEN = Path(__file__).resolve().parents[2] / "scenarios"
SAMPLE = [
    "s01_bad_deploy",
    "s03_config_not_deploy",
    "s05_poison_message",
    "s09_metrics_down",
    "s12_two_causes",
    "s15_rebalance_storm",
]


def _load(name: str) -> Dataset:
    return Dataset.model_validate_json((SCEN / name / "data.json").read_text("utf-8"))


def _log_keys(d: Dataset) -> list[tuple]:  # type: ignore[type-arg]
    return sorted((ln.ts, ln.service, ln.host, ln.level, ln.msg) for ln in d.logs)


@pytest.mark.parametrize("name", SAMPLE)
async def test_logs_metrics_and_changes_survive_the_wire(name: str) -> None:  # covers: R4, R18
    original = _load(name)
    snap, warnings = await ingest_via_mock(original)
    assert warnings == []
    assert _log_keys(snap) == _log_keys(original)  # every line, byte for byte
    for svc, series in original.metrics.items():
        for metric, values in series.items():
            if any(v is not None for v in values):
                assert snap.metrics[svc][metric] == values, (svc, metric)
            else:
                assert metric not in snap.metrics.get(svc, {})  # an all-missing series is absent
    want = [(c.ts, c.kind, c.service, c.ref) for c in original.changes]
    assert sorted((c.ts, c.kind, c.service, c.ref) for c in snap.changes) == sorted(want)
    notes = {(c.service, c.ref): c.note for c in original.changes}
    assert all(
        notes[(c.service, c.ref)] in c.note for c in snap.changes
    )  # adapters only add context


async def test_every_ingested_item_carries_a_verifiable_source() -> None:  # covers: R4
    snap, _ = await ingest_via_mock(_load("s03_config_not_deploy"))
    assert all(ln.source == "datadog" and ln.url for ln in snap.logs)
    assert {c.source for c in snap.changes} <= {"github", "gcp-audit-logs"} and all(
        c.url for c in snap.changes
    )
    cfg = [c for c in snap.changes if c.kind == "config"]
    assert cfg and "BROKER_TIMEOUT_MS 3000 -> 800" in cfg[0].note
    assert "corp.example" not in snap.model_dump_json()  # the acting person's address never arrives


async def test_the_model_is_shown_where_log_lines_came_from() -> None:  # covers: R4
    snap, _ = await ingest_via_mock(_load("s01_bad_deploy"))
    out = await invoke(Store(snap), "query_logs", {"level": "ERROR", "limit": 5})
    shown = render(out)
    assert shown["sources"] and shown["sources"][0].startswith("https://app.datadoghq.com/logs")


async def test_cloudformation_is_an_alternative_change_source() -> None:  # covers: R4
    original = _load("s03_config_not_deploy")
    snap, warnings = await ingest_via_mock(original, cloud="aws")
    assert warnings == []
    cfg = [c for c in snap.changes if c.kind == "config"]
    assert cfg and cfg[0].source == "cloudformation" and cfg[0].service == "broker-gateway"
    assert "BROKER_TIMEOUT_MS 3000 -> 800" in cfg[0].note


async def test_rate_limits_are_retried_and_the_snapshot_is_still_exact() -> None:  # covers: R5, R9
    original = _load("s01_bad_deploy")
    snap, warnings = await ingest_via_mock(original, Faults(rate_limit_every=3))
    assert warnings == [] and _log_keys(snap) == _log_keys(original)


async def test_an_outage_of_one_provider_degrades_gracefully() -> None:  # covers: R5, R10
    original = _load("s03_config_not_deploy")
    snap, warnings = await ingest_via_mock(
        original, Faults(fail_prefix="/v2")
    )  # GCP audit logs down
    assert len(warnings) == 1 and "GcpAuditLogs" in warnings[0]
    assert _log_keys(snap) == _log_keys(original) and not [
        c for c in snap.changes if c.kind == "config"
    ]


async def test_bad_credentials_become_a_warning_not_a_crash() -> None:  # covers: R5
    snap, warnings = await ingest_via_mock(_load("s01_bad_deploy"), dd_key="wrong")
    assert (
        any("logs unavailable" in w and "authentication" in w for w in warnings) and snap.logs == []
    )


async def test_investigators_reach_the_same_conclusion_on_the_wire_ingested_data() -> (
    None
):  # covers: R1, R11
    original = _load("s01_bad_deploy")
    snap, _ = await ingest_via_mock(original)
    direct = await investigate(Store(original), LlmFactory("fake", script=Team()))
    via_wire = await investigate(Store(snap), LlmFactory("fake", script=Team()))
    assert via_wire.report.status == direct.report.status == "ANSWER"
    assert (
        via_wire.report.hypotheses[0].component
        == direct.report.hypotheses[0].component
        == "order-router"
    )


async def test_the_wire_traffic_is_recorded_and_shows_the_retries() -> None:  # covers: R5, R9
    from mockworld.ingest import ingest_with_traffic

    snap, warnings, calls = await ingest_with_traffic(
        _load("s01_bad_deploy"), Faults(rate_limit_every=4)
    )
    assert warnings == [] and snap.logs
    statuses = [s for _, _, s in calls]
    assert 429 in statuses and 200 in statuses  # rejected requests were retried, not dropped
    paths = {p for _, p, _ in calls}
    assert (
        "/api/v2/logs/events/search" in paths
        and "/api/v1/query" in paths
        and "/v2/entries:list" in paths
    )
    assert any(p.endswith("/deployments") for p in paths)
    # bounded: retries never explode the request count (here ~25% of requests are rejected)
    ok = statuses.count(200)
    assert len(calls) <= ok * 2
