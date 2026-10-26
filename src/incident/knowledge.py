"""What the team knows before it looks at any telemetry: the system catalogue and past incidents.

The catalogue describes the system as it normally is (services, who calls whom, queues, the metrics
each service exports, code modules, database tables, config). It is written ahead of time, never
from the incident's own data, so it saves discovery calls without hinting at what broke, and it may
be stale (the agents verify topology with get_dependencies).
Past incidents come from Memory with their provenance. A CONFIRMED one on the component the
evidence now points to, with a cause label sharing a word, contributes its fix as a candidate
action labelled as history. Neither is ever evidence about this incident or changes the status.
"""

from pathlib import Path

from incident.messages import Action, EvidenceDraft, PastIncident, RankedHypothesis, cause_words
from incident.models import QueueDef, Strict
from incident.state import Board


class ServiceInfo(Strict):
    name: str
    purpose: str = ""
    calls: list[str] = []
    metrics: list[str] = []


class Module(Strict):
    path: str
    service: str = ""
    doc: str = ""


class Table(Strict):
    name: str
    columns: list[str]


class Catalogue(Strict):
    system: str
    services: list[ServiceInfo]
    queues: list[QueueDef] = []
    modules: list[Module] = []
    tables: list[Table] = []
    config: dict[str, str] = {}


def load(path: Path) -> Catalogue:
    return Catalogue.model_validate_json(path.read_text("utf-8"))


def render(cat: Catalogue) -> str:
    lines = [f"SYSTEM CATALOGUE ({cat.system}; static, may be stale; context, not evidence):"]
    for s in cat.services:
        bits = [s.purpose] if s.purpose else []
        bits += [f"calls {', '.join(s.calls)}"] if s.calls else []
        bits += [f"metrics {', '.join(s.metrics)}"] if s.metrics else []
        lines.append(f"- {s.name}: {'; '.join(bits)}" if bits else f"- {s.name}")
    lines += [f"- queue {q.name}: {q.publisher} -> {q.consumer}" for q in cat.queues]
    lines += [
        f"- code {m.path}{f' ({m.service})' if m.service else ''}: {m.doc}" for m in cat.modules
    ]
    lines += [f"- table {t.name}({', '.join(t.columns)})" for t in cat.tables]
    lines += [f"- config {k} = {v}" for k, v in cat.config.items()]
    return "\n".join(lines)


def _provenance(p: PastIncident) -> str:
    if p.confirmed is True:
        return "CONFIRMED by on-call"
    if p.confirmed is False:
        return f"agent conclusion REJECTED by on-call (actual: {p.actual or 'unknown'})"
    return "UNCONFIRMED agent conclusion" if p.status == "ANSWER" else "previously INCONCLUSIVE"


def past_lines(past: list[PastIncident]) -> str:
    if not past:
        return ""
    head = "SIMILAR PAST INCIDENTS (memory; hints to check, never evidence about this incident):"
    rows = [
        f"- {p.id} ({p.date}) [{_provenance(p)}] {p.component}/{p.cause_type}: {p.statement}. "
        f"Fix then: {p.fix}"
        for p in past
    ]
    return "\n".join([head, *rows])


def context_text(cat: Catalogue | None, past: list[PastIncident]) -> str:
    return "\n\n".join(t for t in (render(cat) if cat else "", past_lines(past)) if t)


def matches(p: PastIncident, top: RankedHypothesis) -> bool:
    return (
        p.confirmed is True
        and p.component == top.component
        and bool(cause_words(p.cause_type) & cause_words(top.cause_type))
    )


def past_fix_actions(board: Board, top: RankedHypothesis) -> list[Action]:
    """Candidate fixes from confirmed look-alikes; each cites a history ASSUMPTION it adds."""
    out = []
    for p in (p for p in board.past if matches(p, top) and p.fix):
        ev = board.add_evidence(
            EvidenceDraft(
                kind="ASSUMPTION",
                claim=f"History: {p.id} ({p.date}) on {p.component} was confirmed as "
                f"{p.cause_type} ({p.statement}) and fixed by: {p.fix}",
                service=p.component,
            ),
            "reporting",
            0.5,
            ["history"],
        )
        out.append(
            Action(
                text=f"[from history: {p.id}] {p.fix}",
                rationale="A confirmed past incident on the same component with a similar cause "
                "was fixed this way; verify it applies to this incident before acting.",
                evidence_ids=[ev.id],
                priority="follow_up",
                source="history",
            )
        )
    return out
