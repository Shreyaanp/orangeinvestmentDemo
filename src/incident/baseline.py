"""Single-agent baseline: one agent, the same five tools, the same budget, the same scoring.

Differences from the multi-agent system are only structural: one agent plans, investigates and
concludes in one pass, with no critic and no feedback loop. Grounding, confidence, status and the
report schema are the same code, so the comparison is fair.
"""

import time
from pathlib import Path

from incident import grounding, scoring
from incident.agents.common import (
    Ctx,
    Outcome,
    guarded,
    known,
    prime,
    prompt_text,
    recall,
    remember,
    run_json,
    save_board,
)
from incident.agents.tools import tools_for
from incident.knowledge import Catalogue
from incident.llm import LlmFactory
from incident.memory import Memory
from incident.messages import BaselineResult, ReasoningResult, ReportDraft
from incident.report import assemble
from incident.state import Board, Limits
from incident.tools.registry import DIGEST_NAMES, TOOLS, app_tools
from incident.tools.store import Store
from incident.trace import Trace


def _fold(ctx: Ctx, res: BaselineResult) -> ReportDraft:
    """Ground the baseline's evidence and register its hypotheses on a board, like any other run."""
    b, refs = ctx.board, {}
    for d in res.evidence:
        g = grounding.check_evidence(d, ctx.store.results)
        if g.ok:
            ev = b.add_evidence(d, "reasoning", g.reliability, g.flags)
            refs[d.ref or ev.id] = ev.id
        else:
            b.rejected.append(f"baseline: {g.reason}")
    drafts = [
        h.model_copy(update={
            "supporting": [refs[r] for r in h.supporting if r in refs],
            "contradicting": [refs[r] for r in h.contradicting if r in refs],
            "uncorroborated": [refs[r] for r in h.uncorroborated if r in refs],
            "discriminating_checks": [],
        })
        for h in res.hypotheses
    ]  # fmt: skip
    b.upsert_hypotheses(ReasoningResult(hypotheses=drafts))
    b.notes.extend(res.unresolved)
    actions = [
        a.model_copy(update={"evidence_ids": [refs.get(i, i) for i in a.evidence_ids]})
        for a in res.actions
    ]
    return ReportDraft(
        summary=res.summary, hypotheses=[], actions=actions, unresolved=res.unresolved
    )


def _prompt(store: Store, board: Board) -> str:
    data = store.data
    return (
        f"INCIDENT (reported {data.incident.reported_at:%Y-%m-%d %H:%M} UTC): "
        f"{board.incident_text}\n"
        f"SERVICES: {', '.join(data.topology.services)}\n"
        f"QUEUES: {', '.join(q.name for q in data.topology.queues)}"
        f"{known(board)}"
    )


def start(
    store: Store,
    factory: LlmFactory,
    limits: Limits | None,
    trace: Trace | None,
    run_dir: Path | None,
    memory: Memory | None,
    incident_id: str,
    catalogue: Catalogue | None,
) -> Ctx:
    board = Board(incident_text=store.data.incident.text, limits=limits or Limits())
    prime(board, catalogue, recall(memory, store, incident_id))
    ctx = Ctx(board=board, store=store, factory=factory, trace=trace or Trace(), run_dir=run_dir)
    ctx.max_llm_calls = 40
    return ctx


async def solve(ctx: Ctx) -> tuple[ReportDraft | None, str | None]:
    """One agent investigates with every tool and full context; its evidence is grounded."""
    store, board = ctx.store, ctx.board
    names = list(TOOLS) + app_tools(store.data) + (DIGEST_NAMES if board.limits.lean else [])
    res, err = await guarded(
        run_json(
            ctx,
            name="baseline",
            role="baseline",
            instruction=prompt_text("baseline", board.limits.lean),
            prompt=_prompt(store, board),
            model=BaselineResult,
            tools=tools_for(names, ctx, "B"),
            key="baseline",
        )
    )
    draft = _fold(ctx, res) if res else None
    ctx.trace.emit("investigated", evidence=len(board.evidence), hypotheses=len(board.hypotheses))
    return draft, err


async def investigate_baseline(
    store: Store,
    factory: LlmFactory,
    *,
    limits: Limits | None = None,
    trace: Trace | None = None,
    run_dir: Path | None = None,
    memory: Memory | None = None,
    incident_id: str = "run",
    catalogue: Catalogue | None = None,
) -> Outcome:
    ctx = start(store, factory, limits, trace, run_dir, memory, incident_id, catalogue)
    draft, err = await solve(ctx)
    board = ctx.board
    board.elapsed_s = time.monotonic() - ctx.t0
    verdict = scoring.verdict(board)
    ctx.trace.emit("final", status=verdict.status, error=err)
    report = assemble(board, verdict, draft, f"baseline error: {err}" if err else "")
    save_board(ctx)
    remember(memory, store, board, report, incident_id)
    return Outcome(report=report, board=board, trace=ctx.trace)
