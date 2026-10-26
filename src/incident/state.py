"""The blackboard: shared investigation state, task dependencies, budgets. Serialisable.

Mutators are plain synchronous methods: asyncio is single-threaded and no mutator awaits,
so each call is atomic with respect to the other agents running concurrently.
"""

import re

from incident.messages import (
    AgentName,
    Challenge,
    ChallengeDraft,
    Evidence,
    EvidenceDraft,
    Flag,
    Gap,
    Hypothesis,
    Origin,
    PastIncident,
    ReasoningResult,
    Specialist,
    Task,
)
from incident.models import Strict


class Limits(Strict):
    max_rounds: int = 3
    max_tool_calls: int = 70
    max_tokens: int = 600_000
    max_seconds: float = 420.0
    margin: float = 0.25  # top hypothesis must lead non-compatible rivals by this much
    min_confidence: float = 0.40  # below this the answer is INCONCLUSIVE
    weak_contra: float = (
        0.3  # an uncorroborated (not refuting) fact counts this share of a contradiction
    )
    contra_weight: float = 1.25  # one contradicting fact outweighs this many supporting ones
    contra_limit: float = 0.75  # leader's contradiction must stay below this share of its support
    lean: bool = False  # opt-in efficiency profile: digest tools + shorter evidence
    saturation: float = 2.0  # confidence = score / (score + saturation)


class Usage(Strict):
    tool_calls: int = 0
    tool_attempts: int = 0
    llm_calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    models: dict[str, int] = {}


class Board(Strict):
    incident_text: str
    limits: Limits = Limits()
    usage: Usage = Usage()
    past: list[PastIncident] = []  # recalled from memory before the investigation starts
    context: str = ""  # catalogue + past incidents, shown to planner, specialists and baseline
    round: int = 0
    elapsed_s: float = 0.0
    evidence: dict[str, Evidence] = {}
    hypotheses: dict[str, Hypothesis] = {}
    tasks: dict[str, Task] = {}
    challenges: dict[str, Challenge] = {}
    gaps: list[Gap] = []  # structural: failed or partial tool calls (cap confidence)
    notes: list[str] = []  # things specialists could not verify (reported, do not cap)
    rejected: list[str] = []  # reasons evidence or links were refused (hallucination metric)

    def add_evidence(
        self, d: EvidenceDraft, author: AgentName, reliability: float, flags: list[Flag]
    ) -> Evidence:
        ev = Evidence(
            **d.model_dump(),
            id=f"E-{len(self.evidence) + 1:03d}",
            author=author,
            reliability=reliability,
            flags=flags,
        )
        self.evidence[ev.id] = ev
        return ev

    def add_gap(self, description: str, call_id: str | None = None) -> Gap:
        gap = Gap(id=f"G{len(self.gaps) + 1}", description=description, call_id=call_id)
        self.gaps.append(gap)
        return gap

    def open_gaps(self) -> int:
        return sum(1 for g in self.gaps if not g.resolved)

    def add_task(
        self,
        agent: Specialist,
        goal: str,
        hints: list[str] | None = None,
        depends_on: list[str] | None = None,
        origin: Origin = "plan",
        challenge_id: str | None = None,
    ) -> Task:
        task = Task(
            id=f"T{len(self.tasks) + 1}",
            agent=agent,
            goal=goal,
            hints=hints or [],
            depends_on=depends_on or [],
            origin=origin,
            challenge_id=challenge_id,
        )
        self.tasks[task.id] = task
        return task

    def ready_tasks(self) -> list[Task]:
        done = {t.id for t in self.tasks.values() if t.status == "done"}
        return [
            t
            for t in self.tasks.values()
            if t.status == "pending" and all(d in done for d in t.depends_on)
        ]

    def blocked_tasks(self) -> list[Task]:
        """Pending tasks whose dependencies failed: they can never run."""
        dead = {t.id for t in self.tasks.values() if t.status == "failed"}
        return [
            t for t in self.tasks.values() if t.status == "pending" and dead & set(t.depends_on)
        ]

    def upsert_hypotheses(self, result: ReasoningResult) -> list[Hypothesis]:
        out: list[Hypothesis] = []
        for d in result.hypotheses:
            valid = d.id is not None and re.fullmatch(r"H\d+", d.id)
            hid = d.id if valid and d.id else f"H{len(self.hypotheses) + 1}"
            fields = d.model_dump(exclude={"id", "discriminating_checks"})
            for key in ("supporting", "contradicting", "uncorroborated"):
                fields[key] = self._known(fields[key], f"{hid}.{key}")
            hyp = Hypothesis(id=hid, **fields)
            self.hypotheses[hid] = hyp
            out.append(hyp)
        for hid in result.rejected:
            if hid in self.hypotheses:
                self.hypotheses[hid].status = "rejected"
        return out

    def _known(self, ids: list[str], where: str) -> list[str]:
        good = [i for i in ids if i in self.evidence]
        self.rejected += [
            f"{where}: unknown evidence id {i}" for i in ids if i not in self.evidence
        ]
        return good

    def add_challenges(self, drafts: list[ChallengeDraft]) -> list[Challenge]:
        out = []
        for d in drafts:
            ch = Challenge(**d.model_dump(), id=f"C{len(self.challenges) + 1}")
            self.challenges[ch.id] = ch
            out.append(ch)
        return out

    def budget_exceeded(self) -> str | None:
        lim, use = self.limits, self.usage
        if use.tool_calls >= lim.max_tool_calls:
            return f"tool-call limit {lim.max_tool_calls} reached"
        if use.tokens_in + use.tokens_out >= lim.max_tokens:
            return f"token limit {lim.max_tokens} reached"
        if self.elapsed_s >= lim.max_seconds:
            return f"time limit {lim.max_seconds}s reached"
        return None
