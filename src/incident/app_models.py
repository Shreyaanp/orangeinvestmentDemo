"""Records only an application-level dataset has: one per user message, and the code behind
each deploy. Telemetry in such a dataset is counted from these same events."""

from datetime import datetime
from typing import Literal

from incident.base import Strict

MessageStatus = Literal["replied", "failed", "dlq", "in_flight"]


class StageEvent(Strict):
    stage: str  # webhook, queue, worker, session, llm, tool:<name>, sender, delivery
    ts: datetime
    ms: int
    ok: bool
    detail: str = ""


class ToolCallRecord(Strict):
    tool: str
    ok: bool
    ms: int
    result: str  # what came back, or the error text


class Conversation(Strict):
    id: str  # WhatsApp message id
    user: str  # pseudonymous
    received_at: datetime
    kind: str  # text | interactive | image
    intent: str
    text: str
    status: MessageStatus
    attempts: int
    prompt_version: str | None = None
    model: str | None = None
    context: list[str] = []  # what was loaded into the prompt besides the user text
    tool_calls: list[ToolCallRecord] = []
    answer: str | None = None
    delivery: str | None = None
    feedback: Literal["up", "down"] | None = None
    stages: list[StageEvent] = []


class FileDiff(Strict):
    path: str
    additions: int
    deletions: int
    patch: str


class CodeChange(Strict):
    ref: str  # commit sha; deploys of this commit carry the same ref
    service: str
    title: str
    author: str
    pr: int
    merged_at: datetime
    ci: Literal["success", "failure"]
    files: list[FileDiff]
