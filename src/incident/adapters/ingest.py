"""Snapshot ingest: build the same Dataset the simulator makes, from real infrastructure.

A source that fails does not abort the snapshot: the failure is returned as a warning so the
report can say what could not be checked. The saved snapshot is replayable and reviewable.
"""

from collections.abc import Awaitable
from datetime import datetime

from incident.adapters.ports import ChangeFetcher, LogFetcher, MetricFetcher
from incident.models import Change, Dataset, HistoryItem, Incident, LogLine, Series, Topology
from incident.tools.schemas import ToolError


async def _try[T](what: str, call: Awaitable[T], default: T, warnings: list[str]) -> T:
    """Run one source; a typed failure becomes a warning and an empty result, never a crash."""
    try:
        return await call
    except ToolError as e:
        warnings.append(f"{what} unavailable: {e}")
        return default


async def build_dataset(
    *,
    incident_text: str,
    reported_at: datetime,
    start: datetime,
    end: datetime,
    topology: Topology,
    logs: LogFetcher | None = None,
    metrics: MetricFetcher | None = None,
    changes: list[ChangeFetcher] | None = None,
    history: list[HistoryItem] | None = None,
) -> tuple[Dataset, list[str]]:
    warnings: list[str] = []
    svc = topology.services
    lines: list[LogLine] = (
        await _try("logs", logs.logs(svc, start, end), [], warnings) if logs else []
    )
    empty: Series = {s: {} for s in svc}
    series = (
        await _try("metrics", metrics.metrics(svc, start, end), empty, warnings)
        if metrics
        else empty
    )
    found: list[Change] = []
    for source in changes or []:
        what = f"{type(source).__name__} changes"
        found += await _try(what, source.changes(start, end), [], warnings)
    data = Dataset(
        incident=Incident(reported_at=reported_at, text=incident_text),
        start=start,
        minutes=int((end - start).total_seconds() // 60),
        topology=topology,
        logs=sorted(lines, key=lambda ln: ln.ts),
        metrics=series,
        changes=sorted(found, key=lambda c: c.ts),
        history=history or [],
        tool_faults=[],
    )
    return data, warnings
