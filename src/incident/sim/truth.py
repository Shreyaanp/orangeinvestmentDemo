"""Answer key derived from the injected faults. Only eval and the generator read this."""

from datetime import datetime
from typing import Literal

from incident.models import Level, Strict


class Selector(Strict):
    kind: Literal["log", "change", "metric", "conversation", "code"]
    service: str
    level: Level | None = None
    contains: str = ""
    metric: str | None = None
    min_value: float | None = None
    failed_tool: bool = False  # conversation: only messages where a tool call failed
    start: datetime
    end: datetime


class TruthFault(Strict):
    id: str
    role: Literal["primary", "secondary"]
    component: str
    cause_type: str
    description: str = ""
    onset: datetime
    decisive: list[Selector]


class Truth(Strict):
    faults: list[TruthFault]
    answerable: bool
    expected_status: Literal["ANSWER", "INCONCLUSIVE"]
    trap: str
