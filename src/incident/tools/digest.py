"""Deterministic digests: who moved first (get_anomalies), what is new (get_log_patterns).

They compress thousands of points and lines into a short, ordered answer with no model tokens, so
an agent can start from an objective timeline instead of paging through raw data.
"""

import re
import statistics
from datetime import datetime, timedelta

from pydantic import Field

from incident.models import Dataset, Level, NullTolerant, Strict
from incident.tools.logs import RANK
from incident.tools.schemas import InvalidInput, Result, UtcDatetime

ANOMALIES_DESCRIPTION = (
    "Earliest sustained metric deviations across all services and queues, earliest first: "
    "for each (service, metric) the baseline (median of the first baseline_pct of the window), the "
    "onset time of a deviation lasting 3+ minutes, the peak and the direction. Use it first to see "
    "who moved first; then drill into the first movers with query_metrics and query_logs."
)
PATTERNS_DESCRIPTION = (
    "Recurring log patterns (numbers and ids normalised) with counts, first/last seen and how many "
    "occurred in the baseline period versus after it. Patterns NEW after the baseline come first. "
    "Filter by service and minimum level (default WARN)."
)
SUSTAIN = 3  # consecutive minutes a deviation must last to count
ENVELOPE = 1.5  # ... and it must exceed this multiple of the baseline's min-to-max range


class _Window(NullTolerant):
    start: UtcDatetime | None = None
    end: UtcDatetime | None = None
    baseline_pct: float = Field(0.35, ge=0.1, le=0.8)
    top_n: int = Field(12, ge=1, le=40)


class AnomalyQuery(_Window):
    service: str | None = None
    z: float = Field(4.0, ge=1.0, le=20.0)


class PatternQuery(_Window):
    service: str | None = None
    level: Level = "WARN"


class Anomaly(Strict):
    service: str
    metric: str
    onset: datetime
    direction: str
    baseline: float
    peak: float
    change_pct: float | None
    z: float


class Pattern(Strict):
    service: str
    level: str
    template: str
    count: int
    in_baseline: int
    first_seen: datetime
    last_seen: datetime
    example: str


def _span(data: Dataset, q: _Window) -> tuple[int, int, int]:
    """(first minute, last minute, first minute AFTER the baseline period)."""
    lo = 0 if q.start is None else max(0, int((q.start - data.start).total_seconds() // 60))
    hi = (
        data.minutes
        if q.end is None
        else min(data.minutes, int((q.end - data.start).total_seconds() // 60))
    )
    if hi - lo < 6:
        raise InvalidInput("window too short for a baseline comparison (need at least 6 minutes)")
    return lo, hi, lo + max(3, int((hi - lo) * q.baseline_pct))


def _deviation(
    vals: list[float | None], lo: int, cut: int, hi: int, z: float
) -> tuple[int, float, float] | None:
    base = [v for v in vals[lo:cut] if v is not None]
    if len(base) < 3:
        return None
    med = statistics.median(base)
    mad = statistics.median(abs(v - med) for v in base)
    scale = max(1.4826 * mad, 0.02 * abs(med), 1e-6)
    # a real deviation must beat both the robust spread and the whole range seen in the baseline,
    # otherwise noise on tiny or quantised values (0.004 -> 0.006) is flagged as an incident
    need = max(z * scale, ENVELOPE * (max(base) - min(base)))
    run = 0
    for i in range(cut, hi):
        v = vals[i]
        run = run + 1 if v is not None and abs(v - med) >= need else 0
        if run >= SUSTAIN:
            return i - SUSTAIN + 1, med, scale
    return None


def anomalies(data: Dataset, q: AnomalyQuery) -> Result[Anomaly]:
    if q.service and q.service not in data.metrics:
        raise InvalidInput(
            f"unknown service or queue {q.service!r}; known: {', '.join(data.metrics)}"
        )
    lo, hi, cut = _span(data, q)
    out: list[Anomaly] = []
    for svc, series in data.metrics.items():
        for metric, vals in series.items():
            if q.service and svc != q.service:
                continue
            found = _deviation(vals, lo, cut, hi, q.z)
            if found is None:
                continue
            onset, med, scale = found
            after = [v for v in vals[onset:hi] if v is not None]
            peak = max(after, key=lambda v: abs(v - med))
            out.append(
                Anomaly(
                    service=svc,
                    metric=metric,
                    onset=data.start + timedelta(minutes=onset),
                    direction="up" if peak > med else "down",
                    baseline=round(med, 4),
                    peak=round(peak, 4),
                    change_pct=round(100 * (peak - med) / abs(med), 1) if med else None,
                    z=round(abs(peak - med) / scale, 1),
                )
            )
    out.sort(key=lambda a: (a.onset, -a.z))
    return Result(items=out[: q.top_n], total=len(out), truncated=len(out) > q.top_n)


def _template(msg: str) -> str:
    return re.sub(r"\d+(?:\.\d+)?", "#", msg)[:160]


def patterns(data: Dataset, q: PatternQuery) -> Result[Pattern]:
    if q.service and q.service not in data.topology.services:
        raise InvalidInput(
            f"unknown service {q.service!r}; known: {', '.join(data.topology.services)}"
        )
    lo, hi, cut = _span(data, q)
    groups: dict[tuple[str, str, str], list[tuple[datetime, str]]] = {}
    for ln in data.logs:
        minute = int((ln.ts - data.start).total_seconds() // 60)
        if (
            RANK[ln.level] < RANK[q.level]
            or not lo <= minute < hi
            or (q.service and ln.service != q.service)
        ):
            continue
        groups.setdefault((ln.service, ln.level, _template(ln.msg)), []).append((ln.ts, ln.msg))
    cutoff = data.start + timedelta(minutes=cut)
    items = []
    for (svc, level, tmpl), rows in groups.items():
        rows.sort()
        before = sum(1 for ts, _ in rows if ts < cutoff)
        items.append(
            Pattern(
                service=svc,
                level=level,
                template=tmpl,
                count=len(rows),
                in_baseline=before,
                first_seen=rows[0][0],
                last_seen=rows[-1][0],
                example=rows[0][1],
            )
        )
    items.sort(key=lambda p: (p.in_baseline > 0, p.first_seen, -p.count))  # new patterns first
    return Result(items=items[: q.top_n], total=len(items), truncated=len(items) > q.top_n)
