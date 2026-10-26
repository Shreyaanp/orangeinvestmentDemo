"""Dependency agent: deploys, configuration changes, migrations, topology and past incidents."""

from incident.agents.common import Ctx
from incident.agents.specialist import run_specialist
from incident.messages import SpecialistResult, Task
from incident.models import ToolName

TOOLS: list[ToolName] = ["get_changes", "get_dependencies", "search_incidents"]


async def run(ctx: Ctx, task: Task) -> SpecialistResult:
    return await run_specialist(ctx, task, "dependency", TOOLS)
