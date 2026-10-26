"""query_logs: filter and page the log stream."""

from pydantic import Field

from incident.models import Dataset, Level, LogLine, NullTolerant
from incident.tools.schemas import InvalidInput, Result, UtcDatetime

NAME = "query_logs"
DESCRIPTION = (
    "Search service logs. Filters: service, level (minimum severity: DEBUG<INFO<WARN<ERROR), "
    "contains (case-insensitive substring), start/end (ISO 8601). Oldest first unless "
    "newest_first. If `truncated` or `partial` is set, narrow the query or time window."
)
RANK: dict[str, int] = {"DEBUG": 0, "INFO": 1, "WARN": 2, "ERROR": 3}


class Query(NullTolerant):
    service: str | None = None
    level: Level | None = None
    contains: str | None = None
    start: UtcDatetime | None = None
    end: UtcDatetime | None = None
    limit: int = Field(100, ge=1, le=200)
    newest_first: bool = False


def _match(ln: LogLine, q: Query, needle: str | None) -> bool:
    return (
        (q.service is None or ln.service == q.service)
        and (q.level is None or RANK[ln.level] >= RANK[q.level])
        and (needle is None or needle in ln.msg.lower())
        and (q.start is None or ln.ts >= q.start)
        and (q.end is None or ln.ts < q.end)
    )


def run(data: Dataset, q: Query) -> Result[LogLine]:
    if q.service and q.service not in data.topology.services:
        known = ", ".join(data.topology.services)
        raise InvalidInput(f"unknown service {q.service!r}; known services: {known}")
    needle = q.contains.lower() if q.contains else None
    hits = [ln for ln in data.logs if _match(ln, q, needle)]
    items = (hits[::-1] if q.newest_first else hits)[: q.limit]
    cut = len(hits) > len(items)
    note = "more matches exist; narrow the filters or time window" if cut else None
    return Result(items=items, total=len(hits), truncated=cut, note=note)
