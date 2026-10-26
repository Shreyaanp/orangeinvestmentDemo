"""Planner: builds the first task graph from the incident and adds follow-ups without repeats."""

from typing import Any

from incident.agents.common import Ctx, guarded, known, prompt_text, run_json
from incident.messages import Plan, PlanTask, Task

FALLBACK_PLAN = [
    PlanTask(
        agent="observability",
        goal="Scan metrics of the services named in the incident and "
        "their neighbours; find the earliest deviation from baseline.",
    ),
    PlanTask(
        agent="observability",
        goal="Scan WARN and ERROR logs around the incident for the "
        "most significant error patterns and which services emit them first.",
    ),
    PlanTask(
        agent="dependency",
        goal="List deploys, config changes, migrations and flag changes "
        "around the incident time (ask for every kind, not only deploys).",
    ),
    PlanTask(agent="dependency", goal="Map dependencies and queue links of the affected services."),
]


def add_task(
    ctx: Ctx, pt: PlanTask, origin: Any, deps: list[str], challenge: str | None = None
) -> Task | None:
    b, norm = ctx.board, " ".join(pt.goal.lower().split())
    if any(
        t.agent == pt.agent and " ".join(t.goal.lower().split()) == norm for t in b.tasks.values()
    ):
        return None
    return b.add_task(pt.agent, pt.goal, pt.hints, deps, origin, challenge)


async def plan(ctx: Ctx) -> None:
    if ctx.board.tasks:  # resumed run
        return
    prompt = (
        f"INCIDENT: {ctx.board.incident_text}\n"
        f"SERVICES: {', '.join(ctx.store.data.topology.services)}\n"
        f"QUEUES: {', '.join(q.name for q in ctx.store.data.topology.queues)}"
        f"{known(ctx.board)}"
    )
    plan, err = await guarded(
        run_json(
            ctx,
            name="planner",
            role="planner",
            instruction=prompt_text("planner", ctx.board.limits.lean),
            prompt=prompt,
            model=Plan,
            key="planner",
        )
    )
    ctx.trace.emit("plan", error=err, tasks=len(plan.tasks) if plan else 0)
    ids: list[str] = []
    for pt in plan.tasks[:6] if plan and plan.tasks else FALLBACK_PLAN:
        deps = [ids[i] for i in pt.depends_on_goal if 0 <= i < len(ids) and ids[i]]
        task = add_task(ctx, pt, "plan", deps)
        ids.append(task.id if task else "")
