"""Orchestrator: plans, runs specialists in parallel, loops on critic feedback, enforces limits.

Control flow is deterministic code. The LLM plans and judges; it never decides when to stop.
An agent or tool failure is contained and recorded, and the run still ends with a valid Report.
"""

import asyncio
import time
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from google.adk.runners import InMemoryRunner
from google.genai import types

from incident import grounding, scoring
from incident.agents import critic, dependency, observability, planner, reasoning, reporting
from incident.agents.common import (
    Ctx,
    Outcome,
    guarded,
    prime,
    recall,
    remember,
    save_board,
)
from incident.knowledge import Catalogue
from incident.llm import LlmFactory
from incident.memory import Memory
from incident.messages import (
    CheckRequest,
    CriticVerdict,
    PlanTask,
    Report,
    SpecialistResult,
    Task,
)
from incident.report import assemble
from incident.state import Board, Limits
from incident.tools.store import Store
from incident.trace import Trace

MAX_TASK_ATTEMPTS = 2
SPECIALISTS = {"observability": observability.run, "dependency": dependency.run}


def _tick(ctx: Ctx) -> None:
    ctx.board.elapsed_s = time.monotonic() - ctx.t0


def _ground(ctx: Ctx, task: Task, res: SpecialistResult) -> tuple[int, int]:
    b, ok, bad = ctx.board, 0, 0
    for d in res.evidence:
        g = grounding.check_evidence(d, ctx.store.results)
        if g.ok:
            b.add_evidence(d, task.agent, g.reliability, g.flags)
            ok += 1
        else:
            b.rejected.append(f"{task.id}: {g.reason}")
            bad += 1
    b.notes.extend(n for n in res.gaps if n not in b.notes)
    return ok, bad


def _finish(ctx: Ctx, task: Task, res: SpecialistResult | None, err: str | None) -> None:
    b = ctx.board
    if res is None:
        task.error = err
        task.status = "pending" if task.attempts < MAX_TASK_ATTEMPTS else "failed"
        if task.status == "failed":
            b.add_gap(f"task {task.id} ({task.agent}) failed: {err}")
        ctx.trace.emit("task", id=task.id, status=task.status, error=err)
        return
    ok, bad = _ground(ctx, task, res)
    task.status, task.summary = "done", res.summary
    if task.challenge_id:
        b.challenges[task.challenge_id].resolved = True
    ctx.trace.emit("task", id=task.id, agent=task.agent, status="done", evidence=ok, rejected=bad)


async def _run_tasks(ctx: Ctx) -> None:
    """Run ready tasks in parallel waves. Results are applied in task order (stable ids)."""
    b = ctx.board
    while b.budget_exceeded() is None:
        for t in b.blocked_tasks():
            t.status, t.error = "failed", "a dependency failed"
        ready = b.ready_tasks()
        if not ready:
            return
        for t in ready:
            t.status = "running"
            t.attempts += 1
        results = await asyncio.gather(*(guarded(SPECIALISTS[t.agent](ctx, t)) for t in ready))
        for t, (res, err) in zip(ready, results, strict=True):
            _finish(ctx, t, res, err)
        _tick(ctx)
        save_board(ctx)


async def _reason(ctx: Ctx) -> list[CheckRequest]:
    res, err = await guarded(reasoning.run(ctx))
    if res is None:
        ctx.trace.emit("reasoning", error=err)
        return []
    ctx.board.upsert_hypotheses(res)
    ctx.trace.emit("reasoning", hypotheses=len(res.hypotheses), rejected=ctx.board.rejected[-3:])
    return [c for d in res.hypotheses for c in d.discriminating_checks]


def _followups(
    ctx: Ctx, crit: CriticVerdict | None, checks: list[CheckRequest], can_run: bool
) -> int:
    b, new = ctx.board, 0
    if crit and not crit.approve:
        for ch in b.add_challenges(crit.challenges[:3]):
            pt = PlanTask(agent=ch.agent, goal=ch.requested_check, hints=[ch.objection])
            new += bool(can_run and planner.add_task(ctx, pt, "critic", [], ch.id))
    for c in checks[:2] if can_run else []:
        new += bool(planner.add_task(ctx, PlanTask(agent=c.agent, goal=c.check), "reasoning", []))
    return new


async def _loop(ctx: Ctx) -> str:
    """Plan, then rounds of: run tasks, reason, critique. Returns why it stopped early, if so."""
    b = ctx.board
    await planner.plan(ctx)
    save_board(ctx)
    for rnd in range(max(b.round, 1), b.limits.max_rounds + 1):
        b.round = rnd
        await _run_tasks(ctx)
        _tick(ctx)
        if (stop := b.budget_exceeded()) is not None:
            return stop
        checks = await _reason(ctx)
        v = scoring.verdict(b)
        crit, err = await guarded(critic.run(ctx, v))
        ctx.trace.emit("round", n=rnd, status=v.status, margin=v.margin,
                       approve=crit.approve if crit else None, critic_error=err)  # fmt: skip
        save_board(ctx)
        if crit and crit.approve and v.status == "ANSWER":
            return ""
        if not _followups(ctx, crit, checks, can_run=rnd < b.limits.max_rounds):
            return ""
    return ""


async def run_investigation(ctx: Ctx) -> Report:
    b = ctx.board
    stop, err = await guarded(_loop(ctx))
    stop = stop or (f"orchestrator error: {err}" if err else "")
    for ch in b.challenges.values():
        if not ch.resolved:
            b.add_gap(f"unresolved critic challenge {ch.id}: {ch.objection}")
    if not b.hypotheses and b.evidence:
        await _reason(ctx)
    v = scoring.verdict(b)
    draft, rerr = await guarded(reporting.run(ctx, v))
    ctx.trace.emit("report", error=rerr, status=v.status)
    _tick(ctx)
    report = assemble(b, v, draft, stop)
    ctx.trace.emit("final", status=report.status, stats=report.stats.model_dump())
    save_board(ctx)
    return report


class InvestigationAgent(BaseAgent):
    """The Orchestrator as a custom ADK agent: deterministic control flow over LLM sub-agents."""

    ictx: Any = None
    report: Any = None

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event]:
        self.report = await run_investigation(self.ictx)
        text = self.report.model_dump_json()
        yield Event(
            author=self.name, content=types.Content(role="model", parts=[types.Part(text=text)])
        )


async def investigate(
    store: Store,
    factory: LlmFactory,
    *,
    limits: Limits | None = None,
    trace: Trace | None = None,
    run_dir: Path | None = None,
    resume: bool = False,
    memory: Memory | None = None,
    incident_id: str = "run",
    catalogue: Catalogue | None = None,
) -> Outcome:
    past = recall(memory, store, incident_id)
    saved = run_dir / "board.json" if run_dir else None
    if resume and saved and saved.exists():
        board = Board.model_validate_json(saved.read_text("utf-8"))
        for t in board.tasks.values():
            t.status = "pending" if t.status == "running" else t.status
    else:
        board = Board(incident_text=store.data.incident.text, limits=limits or Limits())
        prime(board, catalogue, past)
    ctx = Ctx(board=board, store=store, factory=factory, trace=trace or Trace(), run_dir=run_dir)
    ctx.t0 = time.monotonic() - board.elapsed_s
    agent = InvestigationAgent(name="orchestrator", ictx=ctx)
    runner = InMemoryRunner(agent=agent, app_name="incident")
    session = await runner.session_service.create_session(app_name="incident", user_id="inv")
    start = types.Content(role="user", parts=[types.Part(text=board.incident_text)])
    async for _ in runner.run_async(user_id="inv", session_id=session.id, new_message=start):
        pass
    remember(memory, store, board, agent.report, incident_id)
    return Outcome(report=agent.report, board=board, trace=ctx.trace)
