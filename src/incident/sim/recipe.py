"""Declarative scenario recipe: faults (with effects, signature logs, changes), noise artifacts."""

from datetime import datetime
from typing import Literal

from incident.models import ChangeKind, Edge, HistoryItem, Level, Strict, ToolFault


class Effect(Strict):
    target: str
    metric: str
    op: Literal["add", "mul", "set"]
    value: float
    ramp_min: int = 0
    after_min: int = 0
    decisive: bool = False


class LogRule(Strict):
    service: str
    level: Level
    msg: str
    per_min: float
    after_min: int = 0
    series: str | None = None  # take {placeholders} from another series (e.g. a queue)
    decisive: bool = True  # False for consequence logs that are not evidence of the root cause


class ChangeRule(Strict):
    kind: ChangeKind
    service: str
    ref: str
    note: str
    offset_min: int = 0


class TruthSpec(Strict):
    component: str
    cause_type: str
    description: str = ""


class Fault(Strict):
    id: str
    role: Literal["primary", "secondary", "distractor"]
    truth: TruthSpec | None = None
    at_min: int
    until_min: int | None = None
    effects: list[Effect] = []
    logs: list[LogRule] = []
    changes: list[ChangeRule] = []


class Artifact(Strict):
    kind: Literal["clock_skew", "log_drop", "metric_missing"]
    service: str
    from_min: int = 0
    to_min: int = 10**6
    offset_s: int = 0
    keep_frac: float = 0.0
    metric: str | None = None
    match: str | None = None


class Recipe(Strict):
    id: str
    seed: int
    start: datetime
    minutes: int = 120
    incident_at_min: int
    incident_text: str
    faults: list[Fault]
    artifacts: list[Artifact] = []
    tool_faults: list[ToolFault] = []
    history_extra: list[HistoryItem] = []
    extra_edges: list[Edge] = []  # dependencies this scenario's stack has beyond the shared world
    trap: str
    answerable: bool = True
    expected_status: Literal["ANSWER", "INCONCLUSIVE"] = "ANSWER"
