"""Assemble the final Report: ranking, confidence, status and fact/assumption split are code."""

from incident.grounding import claim_kind, clean_claims
from incident.knowledge import past_fix_actions
from incident.messages import (
    Action,
    Claim,
    Hypothesis,
    RankedHypothesis,
    Report,
    ReportDraft,
    RunStats,
)
from incident.scoring import Ranked, Verdict, label
from incident.state import Board


def _from_ledger(board: Board, ids: list[str]) -> list[Claim]:
    return [
        Claim(text=board.evidence[i].claim, evidence_ids=[i]) for i in ids if i in board.evidence
    ]


def _narrative(
    board: Board, h: Hypothesis, draft: ReportDraft | None
) -> tuple[list[Claim], list[Claim], int]:
    note = next((n for n in (draft.hypotheses if draft else []) if n.hypothesis_id == h.id), None)
    sup, d1 = clean_claims(note.supporting, board.evidence) if note else ([], 0)
    con, d2 = clean_claims(note.contradicting, board.evidence) if note else ([], 0)
    return (
        sup or _from_ledger(board, h.supporting),
        con or _from_ledger(board, h.contradicting),
        d1 + d2,
    )


def _ranked(
    board: Board, ranked: list[Ranked], draft: ReportDraft | None
) -> tuple[list[RankedHypothesis], int]:
    out, dropped = [], 0
    for i, r in enumerate(ranked, 1):
        sup, con, d = _narrative(board, r.hypothesis, draft)
        dropped += d
        h = r.hypothesis
        out.append(
            RankedHypothesis(
                rank=i, hypothesis_id=h.id, statement=h.statement, component=h.component,
                cause_type=h.cause_type, score=r.score, confidence=r.confidence,
                label=label(r.confidence), supporting=sup, contradicting=con,
            )
        )  # fmt: skip
    return out, dropped


def _actions(board: Board, draft: ReportDraft | None) -> tuple[list[Action], int]:
    actions = draft.actions if draft else []
    kept = [
        a for a in actions if a.evidence_ids and all(i in board.evidence for i in a.evidence_ids)
    ]
    return kept, len(actions) - len(kept)


def assemble(board: Board, verdict: Verdict, draft: ReportDraft | None, stop: str = "") -> Report:
    hyps, dropped = _ranked(board, verdict.ranked, draft)
    cited = {i for h in hyps for c in (*h.supporting, *h.contradicting) for i in c.evidence_ids}
    claims = [Claim(text=board.evidence[i].claim, evidence_ids=[i]) for i in sorted(cited)]
    actions, lost = _actions(board, draft)
    if verdict.status == "ANSWER" and hyps:
        actions += past_fix_actions(board, hyps[0])
    open_gaps = [g.description for g in board.gaps if not g.resolved]
    unresolved = list(
        dict.fromkeys([*(draft.unresolved if draft else []), *open_gaps, *board.notes])
    )
    reason = verdict.reason + (f"; stopped early: {stop}" if stop else "")
    use = board.usage
    return Report(
        status=verdict.status,
        status_reason=reason,
        summary=draft.summary if draft else "No narrative available; see ranked hypotheses.",
        hypotheses=hyps,
        facts=[c for c in claims if claim_kind(c, board.evidence) == "FACT"],
        assumptions=[c for c in claims if claim_kind(c, board.evidence) == "ASSUMPTION"],
        unresolved=unresolved,
        actions=actions,
        stats=RunStats(
            tool_calls=use.tool_calls, tool_attempts=use.tool_attempts, llm_calls=use.llm_calls,
            tokens_in=use.tokens_in, tokens_out=use.tokens_out, models=dict(use.models),
            rounds=board.round,
            elapsed_s=round(board.elapsed_s, 1),
        ),
        dropped_claims=dropped + lost,
    )  # fmt: skip
