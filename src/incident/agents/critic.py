"""Critic agent: challenges the leading hypothesis and asks for more evidence when it is thin."""

from incident.agents.common import Ctx, prompt_text, run_json
from incident.agents.views import (
    challenge_lines,
    evidence_lines,
    gap_lines,
    hypothesis_lines,
    task_lines,
)
from incident.messages import CriticVerdict
from incident.scoring import Verdict


async def run(ctx: Ctx, v: Verdict) -> CriticVerdict:
    b = ctx.board
    left = b.limits.max_rounds - b.round
    prompt = (
        f"INCIDENT: {b.incident_text}\n"
        f"ROUND {b.round} of {b.limits.max_rounds} ({left} follow-up round(s) remain)\n\n"
        f"CODE VERDICT: {v.status} (margin {v.margin}): {v.reason}\n\n"
        f"HYPOTHESES (confidence computed by code from evidence):\n{hypothesis_lines(v.ranked)}\n\n"
        f"EVIDENCE LEDGER:\n{evidence_lines(b, digest=b.limits.lean)}\n\n"
        f"PREVIOUS CHALLENGES (do not repeat resolved ones):\n{challenge_lines(b)}\n\n"
        f"TASKS AND RESULTS:\n{task_lines(b)}\n\nOPEN GAPS AND UNVERIFIED POINTS:\n{gap_lines(b)}"
    )
    return await run_json(
        ctx,
        name="critic",
        role="critic",
        instruction=prompt_text("critic", b.limits.lean),
        prompt=prompt,
        model=CriticVerdict,
        key=f"critic/r{b.round}",
    )
