"""Run one task on a tool-using specialist (observability or dependency)."""

from datetime import timedelta

from incident.agents.common import Ctx, known, prompt_text, run_json
from incident.agents.tools import tools_for
from incident.agents.views import evidence_lines
from incident.llm import Role
from incident.messages import SpecialistResult, Task
from incident.models import ToolName
from incident.tools.registry import DIGEST_NAMES, app_tools


async def run_specialist(
    ctx: Ctx, task: Task, name: Role, tools: list[ToolName]
) -> SpecialistResult:
    data, b = ctx.store.data, ctx.board
    end = data.start + timedelta(minutes=data.minutes)
    prompt = (
        f"INCIDENT (reported {data.incident.reported_at:%Y-%m-%d %H:%M} UTC): {b.incident_text}\n"
        f"Data covers {data.start:%Y-%m-%d %H:%M} to {end:%Y-%m-%d %H:%M} UTC.\n"
        f"SERVICES: {', '.join(data.topology.services)}\n"
        f"QUEUES: {', '.join(q.name for q in data.topology.queues)}\n{known(b)}\n"
        f"YOUR TASK {task.id}: {task.goal}\n"
        + "".join(f"HINT: {h}\n" for h in task.hints)
        + f"\nCLAIMS ALREADY ESTABLISHED (do not repeat):\n{evidence_lines(b, with_excerpt=False)}"
    )
    return await run_json(
        ctx,
        name=name,
        role=name,
        instruction=prompt_text(name, b.limits.lean),
        prompt=prompt,
        model=SpecialistResult,
        tools=tools_for(
            tools
            + app_tools(data, name)
            + (DIGEST_NAMES if b.limits.lean and name == "observability" else []),
            ctx,
            prefix=task.id,
        ),
        key=f"{name}/{task.id}/a{task.attempts}",
    )
