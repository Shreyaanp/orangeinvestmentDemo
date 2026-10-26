"""Reporting agent: writes narrative and remediation; ranking and confidence come from code."""

from incident.agents.common import Ctx, prompt_text, run_json
from incident.agents.views import evidence_lines, gap_lines, hypothesis_lines
from incident.messages import ReportDraft
from incident.scoring import Verdict


async def run(ctx: Ctx, v: Verdict) -> ReportDraft:
    b = ctx.board
    prompt = (
        f"INCIDENT: {b.incident_text}\n\n"
        f"OUTCOME DECIDED BY CODE: {v.status}. {v.reason}\n"
        "Do not contradict this outcome or restate confidence numbers.\n\n"
        f"RANKED HYPOTHESES:\n{hypothesis_lines(v.ranked)}\n\n"
        "EVIDENCE LEDGER (the only ids you may cite):\n"
        f"{evidence_lines(b, digest=b.limits.lean)}\n\n"
        f"UNRESOLVED:\n{gap_lines(b)}"
    )
    return await run_json(
        ctx,
        name="reporting",
        role="reporting",
        instruction=prompt_text("reporting", b.limits.lean),
        prompt=prompt,
        model=ReportDraft,
        key="reporting",
    )
