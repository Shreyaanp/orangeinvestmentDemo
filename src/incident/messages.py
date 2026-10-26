"""Contracts exchanged between agents and stored on the blackboard. No free-text handoffs."""

import re
from datetime import datetime
from typing import Literal

from incident.models import Lenient, Strict

AgentName = Literal[
    "orchestrator", "observability", "dependency", "reasoning", "critic", "reporting"
]
Specialist = Literal["observability", "dependency"]
Origin = Literal["plan", "reasoning", "critic"]
EvidenceKind = Literal["FACT", "ASSUMPTION"]
Flag = Literal["partial", "truncated", "history", "assumption", "empty"]
ChallengeKind = Literal[
    "correlation_not_causation",
    "missing_coverage",
    "contradiction",
    "weak_evidence",
    "ordering_or_clock",
    "alternative_explanation",
]


class EvidenceDraft(Lenient):
    """What a specialist proposes. A FACT must quote a tool result verbatim."""

    kind: EvidenceKind
    claim: str
    excerpt: str = ""
    source_call_id: str | None = None
    service: str | None = None
    ts: datetime | None = None
    ref: str | None = None  # local label (e1, e2) so a one-shot agent can cite its own evidence


class Evidence(EvidenceDraft):
    id: str
    author: AgentName
    reliability: float
    flags: list[Flag] = []


class Gap(Strict):
    id: str
    description: str
    call_id: str | None = None
    resolved: bool = False


class SpecialistResult(Lenient):
    summary: str
    evidence: list[EvidenceDraft]
    gaps: list[str] = []


class CheckRequest(Lenient):
    agent: Specialist
    check: str


class HypothesisDraft(Lenient):
    id: str | None = None  # H<n>: reuse to update a hypothesis, or pick the next free number
    statement: str
    component: str
    cause_type: str
    supporting: list[str]
    contradicting: list[str] = []
    uncorroborated: list[
        str
    ] = []  # facts that merely fail to confirm it (absence, gaps), not refute it
    compatible_with: list[str] = []  # hypothesis ids that may be true at the same time
    discriminating_checks: list[CheckRequest] = []


def cause_words(label: str | None) -> set[str]:
    """The meaningful words of a cause label ("db_pool_exhaustion" -> pool, exhaustion)."""
    return {w for w in re.findall(r"[a-z]+", (label or "").lower()) if len(w) >= 4}


class Hypothesis(Strict):
    id: str
    statement: str
    component: str
    cause_type: str
    supporting: list[str]
    contradicting: list[str] = []
    uncorroborated: list[str] = []
    compatible_with: list[str] = []
    status: Literal["active", "rejected"] = "active"


class ReasoningResult(Lenient):
    hypotheses: list[HypothesisDraft]
    rejected: list[str] = []


class ChallengeDraft(Lenient):
    target: str
    kind: ChallengeKind
    objection: str
    requested_check: str
    agent: Specialist


class Challenge(ChallengeDraft):
    id: str
    resolved: bool = False


class CriticVerdict(Lenient):
    approve: bool
    rationale: str
    challenges: list[ChallengeDraft] = []


class Task(Strict):
    id: str
    agent: Specialist
    goal: str
    hints: list[str] = []
    depends_on: list[str] = []
    origin: Origin = "plan"
    challenge_id: str | None = None
    status: Literal["pending", "running", "done", "failed"] = "pending"
    attempts: int = 0
    summary: str | None = None
    error: str | None = None


class PlanTask(Lenient):
    agent: Specialist
    goal: str
    hints: list[str] = []
    depends_on_goal: list[int] = []  # indexes of earlier tasks in the same plan


class Plan(Lenient):
    tasks: list[PlanTask]


class Claim(Lenient):
    text: str
    evidence_ids: list[str]


class HypothesisNarrative(Lenient):
    hypothesis_id: str
    supporting: list[Claim]
    contradicting: list[Claim] = []


class Action(Lenient):
    text: str
    rationale: str
    evidence_ids: list[str]
    priority: Literal["immediate", "follow_up"]
    source: Literal["evidence", "history"] = "evidence"


class PastIncident(Strict):
    """A similar past incident recalled from memory: context and candidate fixes, never evidence."""

    id: str
    date: str
    summary: str
    status: str
    component: str | None
    cause_type: str | None
    statement: str | None
    confirmed: bool | None
    actual: str | None = None
    fix: str
    confidence: float | None = None


class ReportDraft(Lenient):
    """What the Reporting agent writes. Ranking, confidence and status are set by code."""

    summary: str
    hypotheses: list[HypothesisNarrative]
    actions: list[Action]
    unresolved: list[str] = []


class BaselineResult(Lenient):
    """The single-agent baseline's one-shot answer; code grounds and scores it like any other."""

    summary: str
    evidence: list[EvidenceDraft]
    hypotheses: list[HypothesisDraft]
    actions: list[Action]
    unresolved: list[str] = []


class RankedHypothesis(Strict):
    rank: int
    hypothesis_id: str
    statement: str
    component: str
    cause_type: str
    score: float
    confidence: float
    label: Literal["high", "medium", "low"]
    supporting: list[Claim]
    contradicting: list[Claim]


class RunStats(Strict):
    tool_calls: int = 0
    tool_attempts: int = 0
    llm_calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    models: dict[str, int] = {}  # model id that answered -> calls, as reported by the backend
    rounds: int = 0
    elapsed_s: float = 0.0


class Report(Strict):
    status: Literal["ANSWER", "INCONCLUSIVE"]
    status_reason: str
    summary: str
    hypotheses: list[RankedHypothesis]
    facts: list[Claim]
    assumptions: list[Claim]
    unresolved: list[str]
    actions: list[Action]
    stats: RunStats
    dropped_claims: int = 0
