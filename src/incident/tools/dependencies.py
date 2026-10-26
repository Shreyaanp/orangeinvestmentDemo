"""get_dependencies: who a service calls, who calls it, and its queue links."""

from typing import Literal

from incident.models import Dataset, NullTolerant, Strict
from incident.tools.schemas import InvalidInput, Result

NAME = "get_dependencies"
DESCRIPTION = (
    "Service topology around one service or queue: synchronous calls (with call weight), "
    "callers, and queues it publishes to or consumes from."
)
Direction = Literal[
    "calls", "called_by", "publishes_to", "consumes_from", "published_by", "consumed_by"
]


class Query(NullTolerant):
    service: str


class Item(Strict):
    direction: Direction
    name: str
    weight: float | None = None


def run(data: Dataset, q: Query) -> Result[Item]:
    topo = data.topology
    queues = {x.name: x for x in topo.queues}
    if q.service not in topo.services and q.service not in queues:
        raise InvalidInput(f"unknown service or queue {q.service!r}")
    items = [
        Item(direction="calls", name=e.callee, weight=e.weight)
        for e in topo.edges
        if e.caller == q.service
    ]
    items += [
        Item(direction="called_by", name=e.caller, weight=e.weight)
        for e in topo.edges
        if e.callee == q.service
    ]
    items += [
        Item(direction="publishes_to", name=x.name) for x in topo.queues if x.publisher == q.service
    ]
    items += [
        Item(direction="consumes_from", name=x.name) for x in topo.queues if x.consumer == q.service
    ]
    if q.service in queues:
        items += [
            Item(direction="published_by", name=queues[q.service].publisher),
            Item(direction="consumed_by", name=queues[q.service].consumer),
        ]
    return Result(items=items, total=len(items))
