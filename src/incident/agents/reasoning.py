"""Reasoning agent: builds and compares competing root-cause hypotheses from the ledger."""

from incident.agents.common import Ctx, known, prompt_text, run_json
from incident.agents.views import (
    challenge_lines,
    evidence_lines,
    gap_lines,
    hypothesis_lines,
    task_lines,
)
from incident.messages import ReasoningResult
from incident.scoring import rank


async def run(ctx: Ctx) -> ReasoningResult:
    b = ctx.board
    prompt = (
        f"INCIDENT: {b.incident_text}\n"
        f"SERVICES: {', '.join(ctx.store.data.topology.services)}\n"
        f"ROUND {b.round} of {b.limits.max_rounds}\n{known(b)}\n"
        f"EVIDENCE LEDGER (cite these ids only):\n{evidence_lines(b, digest=b.limits.lean)}\n\n"
        f"EXISTING HYPOTHESES (with code-computed confidence):\n{hypothesis_lines(rank(b))}\n\n"
        f"CRITIC CHALLENGES:\n{challenge_lines(b)}\n\nTASKS:\n{task_lines(b)}\n\n"
        f"OPEN GAPS AND UNVERIFIED POINTS:\n{gap_lines(b)}"
    )
    return await run_json(
        ctx,
        name="reasoning",
        role="reasoning",
        instruction=prompt_text("reasoning", b.limits.lean),
        prompt=prompt,
        model=ReasoningResult,
        key=f"reasoning/r{b.round}",
    )
