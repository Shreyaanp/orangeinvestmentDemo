"""Baseline world: services, call edges, queues, shared history."""

from pathlib import Path

from incident.models import Edge, HistoryItem, QueueDef, Strict


class ServiceBase(Strict):
    rps: float
    latency_ms: float
    err_rate: float
    gauges: dict[str, float] = {}
    info_logs: list[str] = []
    noise_logs: list[str] = []


class QueueBase(QueueDef):
    base_publish: float
    base_consume: float
    consumers: int


class World(Strict):
    services: dict[str, ServiceBase]
    edges: list[Edge]
    queues: list[QueueBase]
    history: list[HistoryItem]


def load_world(path: Path) -> World:
    return World.model_validate_json(path.read_text(encoding="utf-8"))
