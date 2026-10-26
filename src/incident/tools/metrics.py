"""query_metrics: per-minute time series, summarised or as downsampled points."""

import math
from datetime import datetime, timedelta

from pydantic import Field

from incident.models import Dataset, NullTolerant, Strict
from incident.tools.schemas import InvalidInput, Result, UtcDatetime

NAME = "query_metrics"
DESCRIPTION = (
    "Query metrics for a service or queue. Without `metric` returns one summary "
    "(min/max/mean/last/missing) per metric; with `metric` also returns points downsampled "
    "to step_min minutes. start/end are ISO 8601. Missing points are null, not zero."
)


class Point(Strict):
    ts: datetime
    value: float | None


class Stats(Strict):
    min: float | None
    max: float | None
    mean: float | None
    last: float | None
    missing: int


class MetricItem(Strict):
    service: str
    metric: str
    stats: Stats
    points: list[Point] | None = None


class Query(NullTolerant):
    service: str
    metric: str | None = None
    start: UtcDatetime | None = None
    end: UtcDatetime | None = None
    step_min: int = Field(5, ge=1, le=60)


def _bound(data: Dataset, ts: datetime | None, default: int, up: bool) -> int:
    if ts is None:
        return default
    mins = (ts - data.start).total_seconds() / 60
    return max(0, min(data.minutes, math.ceil(mins) if up else math.floor(mins)))


def _stats(vals: list[float | None]) -> Stats:
    got = [v for v in vals if v is not None]
    return Stats(
        min=min(got, default=None),
        max=max(got, default=None),
        mean=round(sum(got) / len(got), 3) if got else None,
        last=got[-1] if got else None,
        missing=len(vals) - len(got),
    )


def _points(data: Dataset, vals: list[float | None], lo: int, step: int) -> list[Point]:
    out: list[Point] = []
    for i in range(0, len(vals), step):
        got = [v for v in vals[i : i + step] if v is not None]
        mean = round(sum(got) / len(got), 3) if got else None
        out.append(Point(ts=data.start + timedelta(minutes=lo + i), value=mean))
    return out


def run(data: Dataset, q: Query) -> Result[MetricItem]:
    series = data.metrics.get(q.service)
    if series is None:
        raise InvalidInput(
            f"unknown service or queue {q.service!r}; known: {', '.join(data.metrics)}"
        )
    if q.metric and q.metric not in series:
        raise InvalidInput(
            f"unknown metric {q.metric!r} for {q.service}; known: {', '.join(series)}"
        )
    lo, hi = _bound(data, q.start, 0, False), _bound(data, q.end, data.minutes, True)
    items = [
        MetricItem(
            service=q.service,
            metric=name,
            stats=_stats(series[name][lo:hi]),
            points=_points(data, series[name][lo:hi], lo, q.step_min) if q.metric else None,
        )
        for name in ([q.metric] if q.metric else sorted(series))
    ]
    return Result(items=items, total=len(items))
