"""Observability agent: investigates logs and metrics for one task."""

from incident.agents.common import Ctx
from incident.agents.specialist import run_specialist
from incident.messages import SpecialistResult, Task
from incident.models import ToolName

TOOLS: list[ToolName] = ["query_logs", "query_metrics"]


async def run(ctx: Ctx, task: Task) -> SpecialistResult:
    return await run_specialist(ctx, task, "observability", TOOLS)
