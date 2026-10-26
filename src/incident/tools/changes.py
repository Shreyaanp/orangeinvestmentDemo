"""get_changes: deploys, config changes, migrations and flag changes."""

from incident.models import Change, ChangeKind, Dataset, NullTolerant
from incident.tools.schemas import InvalidInput, Result, UtcDatetime

NAME = "get_changes"
DESCRIPTION = (
    "Change history. `kinds` defaults to deploys only; also ask for config, migration and flag "
    "to see configuration changes, database migrations and feature flags. Optional service, "
    "start/end (ISO 8601). Newest last."
)


class Query(NullTolerant):
    service: str | None = None
    kinds: list[ChangeKind] = ["deploy"]
    start: UtcDatetime | None = None
    end: UtcDatetime | None = None


def run(data: Dataset, q: Query) -> Result[Change]:
    if q.service and q.service not in data.topology.services:
        raise InvalidInput(
            f"unknown service {q.service!r}; known: {', '.join(data.topology.services)}"
        )
    items = [
        c
        for c in data.changes
        if c.kind in q.kinds
        and (q.service is None or c.service == q.service)
        and (q.start is None or c.ts >= q.start)
        and (q.end is None or c.ts < q.end)
    ]
    return Result(items=items, total=len(items))
