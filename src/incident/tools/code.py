"""get_code_change: the git commits behind deploys and migrations, with their diffs."""

from incident.app_models import CodeChange, FileDiff
from incident.models import Dataset, NullTolerant
from incident.tools.schemas import InvalidInput, Result, UtcDatetime

NAME = "get_code_change"
DESCRIPTION = (
    "Git commits merged to main: sha (equal to the ref of its deploy or migration in "
    "get_changes), service, title, author, PR number, CI result (ci=failure means the pipeline "
    "failed and the commit was NOT deployed), and per-file unified diffs. Filter by ref, "
    "service, path (substring of a changed file), start/end (ISO 8601, merge time)."
)
PATCH_CHARS = 1500


class Query(NullTolerant):
    ref: str | None = None
    service: str | None = None
    path: str | None = None
    start: UtcDatetime | None = None
    end: UtcDatetime | None = None


def _short(f: FileDiff) -> FileDiff:
    return f.model_copy(update={"patch": f.patch[:PATCH_CHARS]})


def run(data: Dataset, q: Query) -> Result[CodeChange]:
    if not data.code_changes:
        raise InvalidInput("this dataset has no code history")
    if q.service and q.service not in data.topology.services:
        raise InvalidInput(
            f"unknown service {q.service!r}; known: {', '.join(data.topology.services)}"
        )
    items = [
        c.model_copy(update={"files": [_short(f) for f in c.files]})
        for c in data.code_changes
        if (q.ref is None or c.ref.startswith(q.ref))
        and (q.service is None or c.service == q.service)
        and (q.path is None or any(q.path in f.path for f in c.files))
        and (q.start is None or c.merged_at >= q.start)
        and (q.end is None or c.merged_at < q.end)
    ]
    return Result(items=items, total=len(items))
