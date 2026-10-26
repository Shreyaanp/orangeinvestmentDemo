"""message_funnel: where user messages are lost or degraded, per time window."""

from collections import Counter
from datetime import datetime, timedelta

from pydantic import Field

from incident.app_models import Conversation
from incident.models import Dataset, NullTolerant, Strict
from incident.tools.schemas import InvalidInput, Result, UtcDatetime

NAME = "message_funnel"
DESCRIPTION = (
    "User-message funnel per time window: received, replied, failed, dead-lettered (dlq), still "
    "in flight, retried; messages with a failed tool call, messages answered after a tool call "
    "failed, messages answered with extra context loaded (e.g. a cached snapshot), delivery "
    "failures and thumbs-down feedback, plus tool failures by tool. Optional start/end "
    "(ISO 8601, on receive time), step_min (default 15), intent."
)


class Query(NullTolerant):
    start: UtcDatetime | None = None
    end: UtcDatetime | None = None
    step_min: int = Field(15, ge=5, le=60)
    intent: str | None = None


class Window(Strict):
    start: datetime
    received: int
    replied: int
    failed: int
    dlq: int
    in_flight: int
    retried: int
    tool_failed: int
    answered_after_tool_failure: int
    answered_with_context: int
    delivery_failed: int
    thumbs_down: int
    tool_failures: dict[str, int]


def _window(start: datetime, convs: list[Conversation]) -> Window:
    status = Counter(c.status for c in convs)
    broken = [c for c in convs if any(not t.ok for t in c.tool_calls)]
    return Window(
        start=start,
        received=len(convs),
        replied=status["replied"],
        failed=status["failed"],
        dlq=status["dlq"],
        in_flight=status["in_flight"],
        retried=sum(c.attempts > 1 for c in convs),
        tool_failed=len(broken),
        answered_after_tool_failure=sum(c.answer is not None for c in broken),
        answered_with_context=sum(bool(c.context) and c.answer is not None for c in convs),
        delivery_failed=sum((c.delivery or "").startswith("failed") for c in convs),
        thumbs_down=sum(c.feedback == "down" for c in convs),
        tool_failures=dict(Counter(t.tool for c in convs for t in c.tool_calls if not t.ok)),
    )


def run(data: Dataset, q: Query) -> Result[Window]:
    if not data.conversations:
        raise InvalidInput("this dataset has no message-level records")
    intents = sorted({c.intent for c in data.conversations})
    if q.intent and q.intent not in intents:
        raise InvalidInput(f"unknown intent {q.intent!r}; known: {', '.join(intents)}")
    lo = q.start or data.start
    hi = q.end or data.start + timedelta(minutes=data.minutes)
    step = timedelta(minutes=q.step_min)
    picked = [
        c
        for c in data.conversations
        if lo <= c.received_at < hi and (q.intent is None or c.intent == q.intent)
    ]
    items, t = [], lo
    while t < hi:
        items.append(_window(t, [c for c in picked if t <= c.received_at < t + step]))
        t += step
    return Result(items=items, total=len(items))
