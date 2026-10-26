"""Compact text views of the blackboard for agent prompts."""

import re

from incident.messages import Evidence
from incident.scoring import Ranked
from incident.state import Board


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9.]+", text.lower()) if len(w) > 2}


def _merged(board: Board) -> list[tuple[Evidence, list[str]]]:
    """Fold near-identical claims (word overlap >= 0.8) into one row, keeping the most reliable."""
    groups: list[tuple[Evidence, set[str], list[str]]] = []
    for e in sorted(board.evidence.values(), key=lambda x: -x.reliability):
        w = _words(e.claim)
        for rep, rw, extra in groups:
            if rep.service == e.service and len(w & rw) / max(1, len(w | rw)) >= 0.8:
                extra.append(e.id)
                break
        else:
            groups.append((e, w, []))
    return sorted(((rep, extra) for rep, _, extra in groups), key=lambda g: g[0].id)


def evidence_lines(board: Board, with_excerpt: bool = True, digest: bool = False) -> str:
    """digest=True: no quotes and duplicates folded in; ids stay valid to cite."""
    rows = []
    if digest:
        for e, extra in _merged(board):
            more = f" (also {','.join(extra)})" if extra else ""
            rows.append(
                f"{e.id} [{e.kind} r={e.reliability:g}] {e.service or '-'}: {e.claim}{more}"
            )
        return "\n".join(rows) or "(none yet)"
    for e in board.evidence.values():
        tag = f"{e.kind} r={e.reliability:g}" + (f" {','.join(e.flags)}" if e.flags else "")
        when = f" @{e.ts:%H:%M:%S}" if e.ts else ""
        quote = f' | "{e.excerpt[:220]}"' if with_excerpt and e.excerpt else ""
        rows.append(f"{e.id} [{tag}] {e.service or '-'}{when}: {e.claim}{quote}")
    return "\n".join(rows) or "(none yet)"


def hypothesis_lines(ranked: list[Ranked]) -> str:
    rows = []
    for r in ranked:
        h = r.hypothesis
        sup, con = ",".join(h.supporting) or "-", ",".join(h.contradicting) or "-"
        unc = ",".join(h.uncorroborated) or "-"
        rows.append(
            f"{h.id} confidence={r.confidence} [{h.component}/{h.cause_type}] {h.statement} | "
            f"supports: {sup} | contradicts: {con} | uncorroborated: {unc} | "
            f"compatible_with: {','.join(h.compatible_with) or '-'}"
        )
    return "\n".join(rows) or "(none yet)"


def task_lines(board: Board) -> str:
    rows = []
    for t in board.tasks.values():
        tail = t.summary if t.status == "done" else t.error
        rows.append(f"{t.id} [{t.status}] {t.agent}: {t.goal} -> {tail or '-'}")
    return "\n".join(rows) or "(none)"


def challenge_lines(board: Board) -> str:
    rows = [
        f"{c.id} [{'resolved' if c.resolved else 'open'}] vs {c.target} ({c.kind}): {c.objection}"
        for c in board.challenges.values()
    ]
    return "\n".join(rows) or "(none)"


def gap_lines(board: Board) -> str:
    rows = [f"{g.id} [{'resolved' if g.resolved else 'OPEN'}] {g.description}" for g in board.gaps]
    return "\n".join(rows + [f"note: {n}" for n in board.notes]) or "(none)"
