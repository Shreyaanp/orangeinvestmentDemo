import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "orch"))
from team import Team  # noqa: E402

from incident.adapters.cloud import (  # noqa: E402
    CloudFormation,
    GcpAuditLogs,
    map_audit_entries,
    map_stack_events,
)
from incident.adapters.datadog import Datadog, bucket  # noqa: E402
from incident.adapters.github import GitHub  # noqa: E402
from incident.adapters.ingest import build_dataset  # noqa: E402
from incident.adapters.ports import AuthError, Http  # noqa: E402
from incident.llm import LlmFactory  # noqa: E402
from incident.models import Edge, LogLine, Topology  # noqa: E402
from incident.orchestrator import investigate  # noqa: E402
from incident.redact import redact  # noqa: E402
from incident.tools.schemas import ToolError, ToolTimeout, ToolUnavailable  # noqa: E402
from incident.tools.store import Store  # noqa: E402

START = datetime(2026, 4, 1, 12, 0, tzinfo=UTC)
END = datetime(2026, 4, 1, 14, 0, tzinfo=UTC)


async def _nosleep(_: float) -> None:
    return None


def _http(handler) -> Http:  # type: ignore[no-untyped-def]
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return Http(client, retries=2, backoff_s=0, sleep=_nosleep)


# ---------- shared HTTP layer ----------


async def test_http_retries_transient_errors_then_succeeds() -> None:  # covers: R5
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(503) if len(calls) < 3 else httpx.Response(200, json={"ok": True})

    assert await _http(handler).request("GET", "https://x/y") == {"ok": True}
    assert len(calls) == 3


async def test_http_gives_up_after_bounded_retries_with_typed_errors() -> None:  # covers: R5, R9
    n = []

    def always_429(req: httpx.Request) -> httpx.Response:
        n.append(1)
        return httpx.Response(429)

    with pytest.raises(ToolUnavailable):
        await _http(always_429).request("GET", "https://x/y")
    assert len(n) == 3  # 1 try + 2 retries, never unbounded

    def slow(req: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=req)

    with pytest.raises(ToolTimeout):
        await _http(slow).request("GET", "https://x/y")

    def refused(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=req)

    with pytest.raises(ToolUnavailable):
        await _http(refused).request("GET", "https://x/y")


async def test_http_does_not_retry_auth_or_client_errors() -> None:  # covers: R5
    n = []

    def deny(req: httpx.Request) -> httpx.Response:
        n.append(1)
        return httpx.Response(403)

    with pytest.raises(AuthError):
        await _http(deny).request("GET", "https://x/y")
    assert len(n) == 1

    def missing(req: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="nope token=abc123secret")

    with pytest.raises(ToolError) as e:
        await _http(missing).request("GET", "https://x/y")
    assert "abc123secret" not in str(e.value)  # even error bodies are redacted


def test_redaction_removes_secrets_and_personal_addresses() -> None:  # covers: R5
    text = "user a.b@corp.com key AKIAABCDEFGHIJKLMNOP Bearer abcdefghijklmnopqrstu password=hunter2 ok"
    out = redact(text)
    for leaked in ("a.b@corp.com", "AKIAABCDEFGHIJKLMNOP", "abcdefghijklmnopqrstu", "hunter2"):
        assert leaked not in out
    assert out.endswith("ok")


# ---------- Datadog ----------


def _dd_event(ts: str, status: str, msg: str, service: str = "orders") -> dict:  # type: ignore[type-arg]
    return {
        "id": "x",
        "attributes": {
            "timestamp": ts,
            "status": status,
            "message": msg,
            "service": service,
            "host": "h1",
        },
    }


async def test_datadog_logs_request_mapping_redaction_and_pagination() -> None:  # covers: R4
    seen: list[dict] = []  # type: ignore[type-arg]

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        seen.append({"headers": dict(req.headers), "body": body})
        if "cursor" not in body["page"]:
            events = [
                _dd_event("2026-04-01T12:05:00.000Z", "error", "boom for bob@x.io"),
                _dd_event("2026-04-01T12:06:00.000Z", "warning", "slow"),
            ]
            return httpx.Response(200, json={"data": events, "meta": {"page": {"after": "c1"}}})
        return httpx.Response(
            200, json={"data": [_dd_event("2026-04-01T12:07:00.000Z", "info", "ok")], "meta": {}}
        )

    dd = Datadog(_http(handler), "apikey", "appkey")
    lines = await dd.logs(["orders", "payments"], START, END)
    assert [ln.level for ln in lines] == ["ERROR", "WARN", "INFO"]
    assert (
        "bob@x.io" not in lines[0].msg
        and lines[0].source == "datadog"
        and "app.datadoghq.com" in (lines[0].url or "")
    )
    assert (
        seen[0]["headers"]["dd-api-key"] == "apikey"
        and seen[0]["headers"]["dd-application-key"] == "appkey"
    )
    assert seen[0]["body"]["filter"]["query"] == "service:orders OR service:payments"
    assert seen[1]["body"]["page"]["cursor"] == "c1"  # followed the cursor


async def test_datadog_pagination_is_capped() -> None:  # covers: R9
    pages = []

    def endless(req: httpx.Request) -> httpx.Response:
        pages.append(1)
        return httpx.Response(
            200,
            json={
                "data": [_dd_event("2026-04-01T12:05:00Z", "info", "x")],
                "meta": {"page": {"after": "again"}},
            },
        )

    lines = await Datadog(_http(endless), "k", "a", max_pages=3).logs(["orders"], START, END)
    assert len(pages) == 3 and len(lines) == 3


def test_metric_points_are_resampled_to_minutes_with_gaps_kept_as_none() -> None:  # covers: R4
    base = int(START.timestamp() * 1000)
    series = [
        {"pointlist": [[base + 5_000, 10.0], [base + 20_000, 20.0], [base + 3 * 60_000, 7.0]]}
    ]
    assert bucket(series, START, 5) == [15.0, None, None, 7.0, None]


async def test_datadog_metrics_builds_one_query_per_service_and_metric() -> None:  # covers: R4
    queries: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        queries.append(req.url.params["query"])
        return httpx.Response(
            200, json={"series": [{"pointlist": [[int(START.timestamp() * 1000), 1.0]]}]}
        )

    dd = Datadog(_http(handler), "k", "a", metric_queries={"rps": "sum:hits{{service:{svc}}}"})
    out = await dd.metrics(["orders", "payments"], START, END)
    assert queries == ["sum:hits{service:orders}", "sum:hits{service:payments}"]
    assert out["orders"]["rps"][0] == 1.0 and len(out["orders"]["rps"]) == 120


# ---------- GitHub ----------


async def test_github_changes_filter_by_window_and_redact() -> None:  # covers: R4
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/deployments"):
            return httpx.Response(
                200,
                json=[
                    {
                        "sha": "a" * 40,
                        "created_at": "2026-04-01T13:00:00Z",
                        "environment": "prod",
                        "description": "ship v2 token=s3cr3tvalue",
                    },
                    {"sha": "b" * 40, "created_at": "2026-03-01T13:00:00Z", "environment": "prod"},
                ],
            )
        runs = [
            {
                "name": "Deploy to prod",
                "head_sha": "c" * 40,
                "created_at": "2026-04-01T12:30:00Z",
                "html_url": "https://github.com/o/r/actions/runs/9",
                "head_commit": {"message": "fix cache key\n\nbody"},
            },
            {
                "name": "CI tests",
                "head_sha": "d" * 40,
                "created_at": "2026-04-01T12:40:00Z",
                "html_url": "u",
            },
        ]
        return httpx.Response(200, json={"workflow_runs": runs})

    gh = GitHub(_http(handler), "org/orders-svc", token="t")
    changes = await gh.changes(START, END)
    assert [c.ref for c in changes] == ["ccccccc", "aaaaaaa"] and {c.kind for c in changes} == {
        "deploy"
    }
    assert all(c.service == "orders-svc" for c in changes)
    assert changes[0].url == "https://github.com/o/r/actions/runs/9" and changes[0].note.endswith(
        "fix cache key"
    )
    assert "s3cr3tvalue" not in changes[1].note and changes[1].url.endswith("/commit/" + "a" * 40)


async def test_github_commit_diff_is_truncated_and_redacted() -> None:  # covers: R4
    patch = "+ ttl = 3600\n" + "+ " + "x" * 5000 + "\n+ api_key=SUPERSECRETKEY"

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path.endswith("/commits/abc")
        return httpx.Response(
            200,
            json={
                "sha": "abc",
                "html_url": "https://github.com/o/r/commit/abc",
                "commit": {"message": "minor copy change"},
                "files": [
                    {
                        "filename": "cache.py",
                        "status": "modified",
                        "additions": 2,
                        "deletions": 1,
                        "patch": patch,
                    }
                ],
            },
        )

    diff = await GitHub(_http(handler), "o/r").commit("abc")
    assert diff.files[0].filename == "cache.py" and len(diff.files[0].patch) <= 1500
    assert "ttl = 3600" in diff.files[0].patch and diff.url.endswith("/commit/abc")


# ---------- CloudFormation and GCP ----------


CFN = {
    "StackEvents": [
        {
            "StackId": "arn:aws:cloudformation:us-east-1:1:stack/orders/1",
            "EventId": "e" * 30,
            "StackName": "orders",
            "LogicalResourceId": "orders",
            "ResourceType": "AWS::CloudFormation::Stack",
            "ResourceStatus": "UPDATE_COMPLETE",
            "Timestamp": datetime(2026, 4, 1, 12, 50, tzinfo=UTC),
        },
        {
            "StackId": "s",
            "EventId": "f" * 30,
            "StackName": "orders",
            "LogicalResourceId": "Svc",
            "ResourceType": "AWS::ECS::Service",
            "ResourceStatus": "UPDATE_FAILED",
            "ResourceStatusReason": "task failed, key=AKIAABCDEFGHIJKLMNOP",
            "Timestamp": datetime(2026, 4, 1, 12, 55, tzinfo=UTC),
        },
        {
            "StackId": "s",
            "EventId": "g" * 30,
            "StackName": "orders",
            "LogicalResourceId": "Db",
            "ResourceType": "AWS::RDS::DBInstance",
            "ResourceStatus": "UPDATE_IN_PROGRESS",
            "Timestamp": datetime(2026, 4, 1, 12, 56, tzinfo=UTC),
        },
    ]
}


def test_cloudformation_events_become_changes() -> None:  # covers: R4
    changes = map_stack_events(CFN, lambda stack: f"{stack}-svc")
    assert [(c.kind, c.service) for c in changes] == [
        ("config", "orders-svc"),
        ("deploy", "orders-svc"),
    ]
    assert "AKIAABCDEFGHIJKLMNOP" not in changes[1].note and changes[0].source == "cloudformation"


async def test_cloudformation_fetch_uses_the_injected_client_and_window() -> None:  # covers: R4

    class FakeClient:
        def describe_stack_events(self, StackName: str) -> dict:  # type: ignore[type-arg]  # noqa: N803
            assert StackName == "orders"
            return CFN

    cf = CloudFormation(FakeClient(), ["orders"])
    assert len(await cf.changes(START, END)) == 2
    assert await cf.changes(datetime(2026, 4, 1, 12, 52, tzinfo=UTC), END) == await cf.changes(
        datetime(2026, 4, 1, 12, 52, tzinfo=UTC), END
    )
    assert len(await cf.changes(datetime(2026, 4, 1, 12, 52, tzinfo=UTC), END)) == 1


def test_gcp_audit_entries_never_copy_the_acting_person() -> None:  # covers: R4
    resp = {
        "entries": [
            {
                "insertId": "i1" * 8,
                "timestamp": "2026-04-01T12:40:00Z",
                "resource": {"labels": {"service_name": "orders"}},
                "protoPayload": {
                    "methodName": "google.cloud.run.v1.Services.ReplaceService",
                    "resourceName": "namespaces/p/services/orders",
                    "authenticationInfo": {"principalEmail": "dev@corp.com"},
                },
            },
            {
                "insertId": "i2" * 8,
                "timestamp": "2026-04-01T12:45:00Z",
                "resource": {"labels": {}},
                "protoPayload": {
                    "methodName": "SetIamPolicy",
                    "resourceName": "projects/p/topics/t",
                    "authenticationInfo": {"principalEmail": "ops@corp.com"},
                },
            },
        ]
    }
    changes = map_audit_entries(resp, lambda n: n)
    assert [c.kind for c in changes] == ["deploy", "config"] and changes[0].service == "orders"
    assert all(
        "corp.com" not in c.note and c.url and "console.cloud.google.com" in c.url for c in changes
    )


async def test_gcp_fetch_sends_a_windowed_filter() -> None:  # covers: R4
    bodies = []

    def handler(req: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(req.content))
        assert req.headers["authorization"] == "Bearer tok"
        return httpx.Response(200, json={"entries": []})

    await GcpAuditLogs(_http(handler), "proj", "tok").changes(START, END)
    assert (
        "cloudaudit.googleapis.com" in bodies[0]["filter"]
        and START.isoformat() in bodies[0]["filter"]
    )


# ---------- ingest: real-shaped data flows through the unchanged investigators ----------


class FakeLogs:
    async def logs(self, services: list[str], start: datetime, end: datetime) -> list[LogLine]:
        ts = datetime(2026, 4, 1, 13, 10, tzinfo=UTC)
        return [
            LogLine(
                ts=ts,
                service="orders",
                host="h",
                level="ERROR",
                msg=f"unhandled exception in checkout {i}",
                source="datadog",
                url="https://app.datadoghq.com/logs?q=1",
            )
            for i in range(3)
        ]


class DownChanges:
    async def changes(self, start: datetime, end: datetime):  # type: ignore[no-untyped-def]
        raise ToolUnavailable("github is down")


async def _snapshot():  # type: ignore[no-untyped-def]
    gh = GitHub(
        _http(
            lambda r: httpx.Response(
                200,
                json=[]
                if r.url.path.endswith("deployments")
                else {
                    "workflow_runs": [
                        {
                            "name": "Deploy",
                            "head_sha": "c" * 40,
                            "created_at": "2026-04-01T13:05:00Z",
                            "html_url": "https://github.com/o/r/actions/runs/1",
                            "head_commit": {"message": "refactor checkout"},
                        }
                    ]
                },
            )
        ),
        "org/orders",
    )
    topo = Topology(
        services=["orders", "payments"],
        edges=[Edge(caller="orders", callee="payments", weight=0.5)],
        queues=[],
    )
    return await build_dataset(
        incident_text="checkout is failing",
        reported_at=END,
        start=START,
        end=END,
        topology=topo,
        logs=FakeLogs(),
        changes=[gh, DownChanges()],
    )


async def test_snapshot_ingest_records_a_failed_source_as_a_warning_not_a_crash() -> (
    None
):  # covers: R5, R10
    data, warnings = await _snapshot()
    assert (
        data.minutes == 120 and len(data.logs) == 3 and [c.ref for c in data.changes] == ["ccccccc"]
    )
    assert len(warnings) == 1 and "github is down" in warnings[0]


async def test_investigators_run_unchanged_on_an_ingested_snapshot() -> (
    None
):  # covers: R1, R11, R12
    data, _ = await _snapshot()
    out = await investigate(Store(data), LlmFactory("fake", script=Team()))
    assert out.report.hypotheses and out.report.hypotheses[0].component == "orders"
    assert out.board.evidence  # grounded against the adapter's data
