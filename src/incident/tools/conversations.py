"""conversation_trace: single user messages end to end, including what the model saw and said."""

from pydantic import Field

from incident.app_models import Conversation, MessageStatus
from incident.models import Dataset, NullTolerant
from incident.tools.schemas import InvalidInput, Result, UtcDatetime

NAME = "conversation_trace"
DESCRIPTION = (
    "Message-level records, one WhatsApp message end to end: text, intent, status, attempts, "
    "prompt version, model, context loaded into the prompt, tool calls with their results or "
    "errors, the answer sent, delivery, feedback, and per-stage timings. Filter by id, status "
    "(replied|failed|dlq|in_flight), intent, tool_failed (true = a tool call failed), feedback "
    "(up|down), start/end (ISO 8601, receive time). Newest last; at most `limit` records "
    "(default 5, max 20); total is the full match count."
)


class Query(NullTolerant):
    id: str | None = None
    status: MessageStatus | None = None
    intent: str | None = None
    tool_failed: bool | None = None
    feedback: str | None = None
    start: UtcDatetime | None = None
    end: UtcDatetime | None = None
    limit: int = Field(5, ge=1, le=20)


def _match(c: Conversation, q: Query) -> bool:
    failed = any(not t.ok for t in c.tool_calls)
    return (
        (q.id is None or c.id == q.id)
        and (q.status is None or c.status == q.status)
        and (q.intent is None or c.intent == q.intent)
        and (q.tool_failed is None or failed == q.tool_failed)
        and (q.feedback is None or c.feedback == q.feedback)
        and (q.start is None or c.received_at >= q.start)
        and (q.end is None or c.received_at < q.end)
    )


def run(data: Dataset, q: Query) -> Result[Conversation]:
    if not data.conversations:
        raise InvalidInput("this dataset has no message-level records")
    hits = [c for c in data.conversations if _match(c, q)]
    return Result(items=hits[-q.limit :], total=len(hits), truncated=len(hits) > q.limit)
