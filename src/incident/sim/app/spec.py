"""Declarative application world and scenario recipe. Behaviour comes from state keys: the
repo's config/app.json (changed only by commits) plus runtime keys set by console changes,
external conditions, or what a commit's code does."""

from datetime import datetime
from typing import Literal

from incident.models import ChangeKind, Edge, HistoryItem, Level, QueueDef, Strict, ToolFault
from incident.sim.recipe import TruthSpec

Value = float | str | bool


class Intent(Strict):
    name: str
    share: float
    texts: list[str]
    tools: list[str] = []


class Edit(Strict):
    path: str
    find: str  # must occur exactly once in the file; "" creates the file with `replace`
    replace: str


class AppChange(Strict):
    id: str
    kind: ChangeKind
    service: str
    at_min: int
    title: str
    author: str = "dev"
    edits: list[Edit] = []  # a commit, merged, built by CI, then deployed at at_min
    set: dict[str, Value] = {}  # runtime keys this change sets (console change or code effect)
    ci: Literal["success", "failure"] = "success"


class External(Strict):
    id: str
    at_min: int
    until_min: int | None = None
    set: dict[str, Value]


class Decisive(Strict):
    kind: Literal["log", "change", "metric", "conversation", "code"]
    service: str
    contains: str = ""
    level: Level | None = None
    metric: str | None = None
    min_value: float | None = None
    failed_tool: bool = False


class AppFault(Strict):
    id: str
    role: Literal["primary", "secondary"]
    truth: TruthSpec
    cause: str  # id of the AppChange or External that is the fault
    decisive: list[Decisive]


class Drop(Strict):
    """Observability gap: telemetry of a service is lost from from_min on."""

    service: str
    from_min: int = 0
    logs: bool = True
    metrics: bool = True
    traces: bool = True  # strips stage timings and tool calls from conversation records


class AppWorld(Strict):
    services: list[str]
    edges: list[Edge]
    queues: list[QueueDef]
    runtime: dict[str, Value]
    intents: list[Intent]
    kinds: dict[str, float]  # WhatsApp message types and their shares
    users: int
    routine: list[AppChange]  # harmless commits sampled as background noise
    history: list[HistoryItem]


class AppRecipe(Strict):
    id: str
    seed: int
    start: datetime
    minutes: int = 90
    rate_per_min: float = 20.0
    incident_at_min: int
    incident_text: str
    changes: list[AppChange] = []
    externals: list[External] = []
    faults: list[AppFault]
    drops: list[Drop] = []
    tool_faults: list[ToolFault] = []
    history_extra: list[HistoryItem] = []
    trap: str
    answerable: bool = True
    expected_status: Literal["ANSWER", "INCONCLUSIVE"] = "ANSWER"
