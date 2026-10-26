"""Contracts for the data an investigation can see. All cross-component messages are models."""

from datetime import datetime
from typing import Any, Literal

from incident.app_models import CodeChange, Conversation
from incident.base import Lenient, NullTolerant, Strict

__all__ = ["Lenient", "NullTolerant", "Strict"]

Level = Literal["DEBUG", "INFO", "WARN", "ERROR"]
ChangeKind = Literal["deploy", "config", "migration", "flag"]
ToolName = Literal[
    "query_logs",
    "query_metrics",
    "get_changes",
    "get_dependencies",
    "search_incidents",
    "get_anomalies",
    "get_log_patterns",
    "message_funnel",
    "conversation_trace",
    "get_code_change",
]
Series = dict[str, dict[str, list[float | None]]]


class LogLine(Strict):
    ts: datetime
    service: str
    host: str
    level: Level
    msg: str
    source: str | None = None  # where it came from (adapter name); None for simulated data
    url: str | None = None  # a link a human can click to verify it


class Change(Strict):
    ts: datetime
    kind: ChangeKind
    service: str
    ref: str
    note: str
    source: str | None = None  # where it came from (adapter name); None for simulated data
    url: str | None = None  # a link a human can click to verify it


class HistoryItem(Strict):
    id: str
    date: str
    summary: str
    root_cause: str
    fix: str
    source: str | None = None  # where it came from (adapter name); None for simulated data
    url: str | None = None  # a link a human can click to verify it


class Edge(Strict):
    caller: str
    callee: str
    weight: float
    lag_min: int = 0


class QueueDef(Strict):
    name: str
    publisher: str
    consumer: str


class Topology(Strict):
    services: list[str]
    edges: list[Edge]
    queues: list[QueueDef]


class ToolFault(Strict):
    tool: ToolName
    kind: Literal["timeout", "truncate", "partial", "unavailable"]
    on_calls: list[int] = []
    max_results: int | None = None


class Incident(Strict):
    reported_at: datetime
    text: str


class ToolErrorInfo(Strict):
    kind: Literal["timeout", "unavailable", "invalid_input", "error"]
    message: str
    retryable: bool


class ToolOutcome(Strict):
    """What an agent gets back from one tool call (after retries)."""

    call_id: str
    tool: ToolName
    args: dict[str, Any]
    ok: bool
    attempts: int
    result_json: str | None = None
    error: ToolErrorInfo | None = None
    truncated: bool = False
    partial: bool = False


class Dataset(Strict):
    incident: Incident
    start: datetime
    minutes: int
    topology: Topology
    logs: list[LogLine]
    metrics: Series
    changes: list[Change]
    history: list[HistoryItem]
    tool_faults: list[ToolFault]
    # application-level datasets only; their tools are offered when these are non-empty
    conversations: list[Conversation] = []
    code_changes: list[CodeChange] = []
