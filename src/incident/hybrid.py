"""Hybrid: one investigator with full context, then the team's checks on its answer.

The single agent investigates as the baseline does, so no evidence is lost between agents. Its
facts are grounded into the ledger and scored by the same code. The Critic then reviews the answer
once. Its objections become specialist tasks, run in parallel, and Reasoning re-ranks on the
enlarged ledger. One verification round at most; status and confidence stay computed by code.
"""

import time
from pathlib import Path

from incident import baseline, scoring
from incident.agents import critic, reporting
from incident.agents.common import Outcome, guarded, remember, save_board
from incident.knowledge import Catalogue
from incident.llm import LlmFactory
from incident.memory import Memory
from incident.orchestrator import _followups, _reason, _run_tasks
from incident.report import assemble
from incident.state import Limits
from incident.tools.store import Store
from incident.trace import Trace


async def investigate_hybrid(
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
    ctx = baseline.start(store, factory, limits, trace, run_dir, memory, incident_id, catalogue)
    ctx.max_llm_calls = 60  # the investigator's 40 plus one critic round and its follow-ups
    b = ctx.board
    draft, err = await baseline.solve(ctx)
    b.elapsed_s = time.monotonic() - ctx.t0
    b.round = 1
    v = scoring.verdict(b)
    crit, cerr = await guarded(critic.run(ctx, v))
    ctx.trace.emit("round", n=1, status=v.status, margin=v.margin,
                   approve=crit.approve if crit else None, critic_error=cerr)  # fmt: skip
    approved = crit is not None and crit.approve and v.status == "ANSWER"
    if not approved and b.budget_exceeded() is None and _followups(ctx, crit, [], can_run=True):
        b.round = 2
        await _run_tasks(ctx)
        await _reason(ctx)
        v = scoring.verdict(b)
        new, rerr = await guarded(reporting.run(ctx, v))
        draft = new or draft
        ctx.trace.emit("report", error=rerr, status=v.status)
    for ch in b.challenges.values():
        if not ch.resolved:
            b.add_gap(f"unresolved critic challenge {ch.id}: {ch.objection}")
    b.elapsed_s = time.monotonic() - ctx.t0
    v = scoring.verdict(b)
    report = assemble(b, v, draft, f"investigator error: {err}" if err else "")
    ctx.trace.emit("final", status=report.status, stats=report.stats.model_dump())
    save_board(ctx)
    remember(memory, store, b, report, incident_id)
    return Outcome(report=report, board=b, trace=ctx.trace)
