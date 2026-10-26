"""Incident memory: a small property graph (SQLite) of past investigations.

Past findings come back as HINTS with their provenance spelled out (confirmed by on-call, concluded
by the agent and unconfirmed, or later rejected), through the history channel the agents already
treat as weak evidence. They are never presented as facts, so a wrong past conclusion cannot quietly
become a "known cause". Stored text is redacted. The same nodes and edges map onto Neo4j/FalkorDB
when scale needs it.

Nodes: incident, service, cause (component/cause_type), change.
Edges: incident AFFECTED service, incident ROOT_CAUSE cause, cause ON service,
       incident PRECEDED_BY change, service CALLS service (the topology).
"""

import json
import re
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from incident.messages import PastIncident, Report
from incident.models import Change, HistoryItem, Topology
from incident.redact import redact
from incident.retrieval import Retriever, build

SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes(id TEXT PRIMARY KEY, kind TEXT NOT NULL, props TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS edges(src TEXT, dst TEXT, kind TEXT, PRIMARY KEY(src, dst, kind));
CREATE INDEX IF NOT EXISTS edges_dst ON edges(dst, kind);
"""
MIN_SCORE = 0.15


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]{3,}", text.lower()))


def _jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a | b else 0.0


def _props(text: str, when: datetime, report: Report, fix: str) -> dict[str, Any]:
    top = report.hypotheses[0] if report.hypotheses else None
    return {
        "text": redact(text),
        "when": when.isoformat(),
        "status": report.status,
        "component": top.component if top else None,
        "cause_type": top.cause_type if top else None,
        "statement": redact(top.statement) if top else None,
        "confidence": top.confidence if top else None,
        "confirmed": None,
        "actual": None,
        "fix": redact(fix or "; ".join(a.text for a in report.actions[:2])),
    }


class Memory:
    def __init__(
        self, path: Path | str = ":memory:", retrieval: str | Retriever | None = None
    ) -> None:
        """retrieval: "keyword" | "hybrid" | "fake" | a Retriever; None reads RETRIEVAL."""
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.executescript(SCHEMA)
        self.retriever = retrieval if isinstance(retrieval, Retriever) else build(retrieval)

    def _node(self, node_id: str, kind: str, props: dict[str, Any]) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO nodes VALUES (?, ?, ?)", (node_id, kind, json.dumps(props))
        )

    def _edge(self, src: str, dst: str, kind: str) -> None:
        self.db.execute("INSERT OR IGNORE INTO edges VALUES (?, ?, ?)", (src, dst, kind))

    def _props(self, node_id: str) -> dict[str, Any]:
        row = self.db.execute("SELECT props FROM nodes WHERE id = ?", (node_id,)).fetchone()
        return json.loads(row[0]) if row else {}

    def _targets(self, src: str, kind: str) -> set[str]:
        rows = self.db.execute("SELECT dst FROM edges WHERE src = ? AND kind = ?", (src, kind))
        return {r[0] for r in rows}

    def record(
        self,
        *,
        incident_id: str,
        text: str,
        when: datetime,
        services: list[str],
        report: Report,
        topology: Topology | None = None,
        changes: list[Change] | None = None,
        fix: str = "",
    ) -> None:
        """Store an investigation as the agent's own, UNCONFIRMED conclusion."""
        node = f"incident:{incident_id}"
        self._node(node, "incident", _props(text, when, report, fix))
        for svc in services:
            self._node(f"service:{svc}", "service", {})
            self._edge(node, f"service:{svc}", "AFFECTED")
        self._link_cause(node, report)
        for c in (changes or [])[-5:]:
            key = f"change:{c.service}/{c.ref}"
            self._node(key, "change", {"kind": c.kind, "note": redact(c.note)})
            self._edge(node, key, "PRECEDED_BY")
        for e in topology.edges if topology else []:
            self._edge(f"service:{e.caller}", f"service:{e.callee}", "CALLS")
        self.db.commit()

    def _link_cause(self, node: str, report: Report) -> None:
        if not report.hypotheses or report.status != "ANSWER":
            return
        top = report.hypotheses[0]
        cause = f"cause:{top.component}/{top.cause_type}"
        self._node(cause, "cause", {"component": top.component, "cause_type": top.cause_type})
        self._edge(node, cause, "ROOT_CAUSE")
        self._edge(cause, f"service:{top.component}", "ON")

    def confirm(
        self, incident_id: str, correct: bool, actual: str | None = None, fix: str | None = None
    ) -> None:
        """Human feedback: the on-call engineer says whether the conclusion was right."""
        node = f"incident:{incident_id}"
        props = self._props(node)
        if not props:
            raise KeyError(f"unknown incident {incident_id}")
        props.update(confirmed=correct, actual=actual, **({"fix": redact(fix)} if fix else {}))
        self._node(node, "incident", props)
        self.db.commit()

    def _neighbours(self, services: set[str]) -> set[str]:
        out = set(services)
        for s in services:
            rows = self.db.execute(
                "SELECT dst FROM edges WHERE src = ? AND kind = 'CALLS' "
                "UNION SELECT src FROM edges WHERE dst = ? AND kind = 'CALLS'",
                (f"service:{s}", f"service:{s}"),
            )
            out |= {r[0].removeprefix("service:") for r in rows}
        return out

    def similar(
        self, text: str, services: list[str], k: int = 3, exclude: set[str] | None = None
    ) -> list[HistoryItem]:
        return [self.hint(p) for p in self.similar_past(text, services, k, exclude)]

    def similar_past(
        self, text: str, services: list[str], k: int = 3, exclude: set[str] | None = None
    ) -> list[PastIncident]:
        want, near = set(services), self._neighbours(set(services))
        rows = []
        for (node_id,) in self.db.execute(
            "SELECT id FROM nodes WHERE kind = 'incident'"
        ).fetchall():
            incident = node_id.removeprefix("incident:")
            if incident not in (exclude or set()):
                theirs = {s.removeprefix("service:") for s in self._targets(node_id, "AFFECTED")}
                svc = max(_jaccard(want, theirs), 0.6 * _jaccard(near, theirs))
                rows.append((incident, self._props(node_id), svc))
        sims = self._text_similarity(text, [p["text"] for _, p, _ in rows])
        scored = []
        for (incident, props, svc), sim in zip(rows, sims, strict=True):
            score = 0.5 * sim + 0.5 * svc
            score += 0.1 if props["confirmed"] is True else 0.0
            if score >= MIN_SCORE:
                scored.append((score, incident, props))
        scored.sort(key=lambda x: -x[0])
        return [self._past(i, p) for _, i, p in scored[:k]]

    def _text_similarity(self, text: str, docs: list[str]) -> list[float]:
        if self.retriever is None:
            return [_jaccard(_words(text), _words(d)) for d in docs]
        rel = dict(self.retriever.rank(text, docs))
        return [rel.get(i, 0.0) for i in range(len(docs))]

    @staticmethod
    def _past(incident: str, p: dict[str, Any]) -> PastIncident:
        return PastIncident(
            id=incident, date=p["when"][:10], summary=p["text"][:240], status=p["status"],
            component=p["component"], cause_type=p["cause_type"], statement=p["statement"],
            confirmed=p["confirmed"], actual=p["actual"], fix=p["fix"] or "none recorded",
            confidence=p["confidence"],
        )  # fmt: skip

    @staticmethod
    def hint(p: PastIncident) -> HistoryItem:
        cand = f"{p.component}/{p.cause_type}: {p.statement}" if p.component else "no candidate"
        if p.confirmed is True:
            cause = f"[CONFIRMED by on-call] {cand}"
        elif p.confirmed is False:
            cause = (
                "[agent conclusion was REJECTED by on-call; do not repeat it without new "
                f"evidence] {cand} (actual: {p.actual or 'unknown'})"
            )
        elif p.status == "ANSWER":
            cause = f"[agent-concluded, UNCONFIRMED, confidence {p.confidence}] {cand}"
        else:
            cause = f"[previously INCONCLUSIVE; leading candidate only] {cand}"
        return HistoryItem(
            id=p.id, date=p.date, summary=p.summary, root_cause=cause, fix=p.fix, source="memory"
        )

    def priors(self, service: str) -> Counter[str]:
        """How often each cause was CONFIRMED on a service: a base rate, not a verdict."""
        out: Counter[str] = Counter()
        for (node_id,) in self.db.execute(
            "SELECT id FROM nodes WHERE kind = 'incident'"
        ).fetchall():
            props = self._props(node_id)
            if props["confirmed"] is True and props["component"] == service:
                out[props["cause_type"]] += 1
        return out

    def __len__(self) -> int:
        row = self.db.execute("SELECT COUNT(*) FROM nodes WHERE kind = 'incident'").fetchone()
        return int(row[0])
