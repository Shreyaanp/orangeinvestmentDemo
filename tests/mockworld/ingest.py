"""Point the real adapters at the mock infrastructure and ingest a snapshot through the wire."""

from datetime import datetime, timedelta

import httpx
from fastapi import FastAPI

from incident.adapters.cloud import CloudFormation, GcpAuditLogs
from incident.adapters.datadog import Datadog
from incident.adapters.github import GitHub
from incident.adapters.ingest import build_dataset
from incident.adapters.ports import Http
from incident.models import Dataset, Series
from mockworld.apis import DD_KEY, GCP_TOKEN, GH_TOKEN, FakeCloudFormation, Faults, make_app


async def _instant(_: float) -> None:
    return None


def http_for(data: Dataset, faults: Faults | None = None) -> tuple[Http, FastAPI]:
    app = make_app(data, faults)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://mock")
    return Http(client, retries=3, backoff_s=0, sleep=_instant), app


class AllSeries:
    """Ask for every series the system reports (services AND queues), not only declared services."""

    def __init__(self, datadog: Datadog, names: list[str]) -> None:
        self.datadog, self.names = datadog, names

    async def metrics(self, services: list[str], start: datetime, end: datetime) -> Series:
        return await self.datadog.metrics(self.names, start, end)


async def ingest_via_mock(
    data: Dataset,
    faults: Faults | None = None,
    *,
    dd_key: str = DD_KEY,
    cloud: str = "gcp",
) -> tuple[Dataset, list[str]]:
    """Rebuild `data` by calling the Datadog, GitHub and GCP or CloudFormation adapters."""
    snapshot, warnings, _ = await ingest_with_traffic(data, faults, dd_key=dd_key, cloud=cloud)
    return snapshot, warnings


async def ingest_with_traffic(
    data: Dataset,
    faults: Faults | None = None,
    *,
    dd_key: str = DD_KEY,
    cloud: str = "gcp",
) -> tuple[Dataset, list[str], list[tuple[str, str, int]]]:
    """Like ingest_via_mock, and also returns the wire traffic the mock served."""
    http, app = http_for(data, faults)
    names = sorted({m for series in data.metrics.values() for m in series})
    queries = {m: f"avg:incident.{m}{{{{service:{{svc}}}}}}" for m in names}
    datadog = Datadog(http, dd_key, "app-key", page_size=1000, max_pages=20, metric_queries=queries)
    repos = [GitHub(http, f"org/{s}", token=GH_TOKEN, service=s) for s in data.topology.services]
    other = (
        GcpAuditLogs(http, "mock", GCP_TOKEN)
        if cloud == "gcp"
        else CloudFormation(FakeCloudFormation(data), data.topology.services)
    )
    snapshot, warnings = await build_dataset(
        incident_text=data.incident.text,
        reported_at=data.incident.reported_at,
        start=data.start,
        end=data.start + timedelta(minutes=data.minutes),
        topology=data.topology,
        logs=datadog,
        metrics=AllSeries(datadog, list(data.metrics)),
        changes=[*repos, other],
        history=data.history,
    )
    return snapshot, warnings, list(app.state.calls)
