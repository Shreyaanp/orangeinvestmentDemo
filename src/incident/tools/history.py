"""search_incidents: keyword search over past incident summaries (opt-in hybrid: RETRIEVAL)."""

import re

from pydantic import Field

from incident.models import Dataset, HistoryItem, NullTolerant
from incident.retrieval import hybrid_order
from incident.tools.schemas import Result

NAME = "search_incidents"
DESCRIPTION = (
    "Search past incidents by keywords. Past incidents show what happened before; "
    "they may not apply to the current situation."
)


class Query(NullTolerant):
    query: str = Field(min_length=2)
    limit: int = Field(3, ge=1, le=10)


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) >= 3}


def run(data: Dataset, q: Query) -> Result[HistoryItem]:
    docs = [f"{h.summary} {h.root_cause} {h.fix}" for h in data.history]
    order = hybrid_order(q.query, docs)  # None unless RETRIEVAL opts in
    if order is None:
        want = _tokens(q.query)
        scored = sorted(
            ((len(want & _tokens(d)), i) for i, d in enumerate(docs)), key=lambda s: -s[0]
        )
        order = [i for n, i in scored if n > 0]
    items = [data.history[i] for i in order][: q.limit]
    return Result(items=items, total=len(order), truncated=len(order) > len(items))
