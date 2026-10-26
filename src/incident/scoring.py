"""Confidence and the ANSWER / INCONCLUSIVE verdict, computed by code from the evidence.

The model proposes hypotheses and cites evidence; it never states a confidence number.

Principles:
* Evidence that every hypothesis explains (the symptom itself, "traffic was normal") does not
  favour any of them: a fact cited as support by k active hypotheses is worth 1/k to each.
* One contradicting fact outweighs 1.5 supporting ones.
* A leader that the evidence substantially contradicts cannot be an ANSWER, even if its rivals are
  contradicted more: winning by elimination is not the same as being established.
"""

from collections import Counter
from typing import Literal

from incident.messages import Hypothesis, cause_words
from incident.models import Strict
from incident.state import Board

GAP_PENALTY = 0.1  # each unresolved evidence gap lowers the confidence ceiling
CEILING, FLOOR = 0.9, 0.5


class Ranked(Strict):
    hypothesis: Hypothesis
    score: float
    confidence: float
    support: float = 0.0
    contra: float = 0.0


class Verdict(Strict):
    status: Literal["ANSWER", "INCONCLUSIVE"]
    ranked: list[Ranked]
    margin: float
    reason: str


def label(confidence: float) -> Literal["high", "medium", "low"]:
    return "high" if confidence >= 0.7 else "medium" if confidence >= 0.45 else "low"


def _weights(board: Board, h: Hypothesis, shared: Counter[str]) -> tuple[float, float]:
    ev = board.evidence
    support = sum(ev[i].reliability / shared[i] for i in set(h.supporting) if i in ev)
    contra = sum(ev[i].reliability for i in set(h.contradicting) if i in ev)
    weak = set(h.uncorroborated) - set(h.contradicting)
    contra += board.limits.weak_contra * sum(ev[i].reliability for i in weak if i in ev)
    return support, contra


def rank(board: Board) -> list[Ranked]:
    ceiling = max(FLOOR, CEILING - GAP_PENALTY * board.open_gaps())
    lim = board.limits
    active = [h for h in board.hypotheses.values() if h.status == "active"]
    shared = Counter(i for h in active for i in set(h.supporting))
    out = []
    for h in active:
        support, contra = _weights(board, h, shared)
        s = max(0.0, support - lim.contra_weight * contra)
        conf = round(min(s / (s + lim.saturation), ceiling), 3)
        out.append(
            Ranked(
                hypothesis=h,
                score=round(s, 3),
                confidence=conf,
                support=round(support, 3),
                contra=round(contra, 3),
            )
        )
    return sorted(out, key=lambda r: -r.confidence)


def _rival(t: Hypothesis, h: Hypothesis) -> bool:
    """A near-synonym on the same component (a shared cause word, e.g. two wordings of one
    dependency slowdown) is the same answer, not a rival; otherwise `compatible_with` (independent
    co-causes, as the model judged them) decides."""
    if h.component == t.component and cause_words(h.cause_type) & cause_words(t.cause_type):
        return False
    return h.id not in t.compatible_with and t.id not in h.compatible_with


def _rivals(top: Ranked, rest: list[Ranked]) -> list[Ranked]:
    return [r for r in rest if _rival(top.hypothesis, r.hypothesis)]


def verdict(board: Board) -> Verdict:
    ranked = rank(board)
    if not ranked:
        return Verdict(
            status="INCONCLUSIVE", ranked=[], margin=0.0, reason="no supported hypothesis"
        )
    top, lim = ranked[0], board.limits
    rival = max((r.confidence for r in _rivals(top, ranked[1:])), default=0.0)
    margin = round(top.confidence - rival, 3)
    reason = ""
    if top.confidence < lim.min_confidence:
        reason = f"top confidence {top.confidence} is below {lim.min_confidence}"
    elif top.contra > lim.contra_limit * top.support:
        reason = (
            f"the leading hypothesis is itself substantially contradicted "
            f"(against {top.contra} vs credited support {top.support})"
        )
    elif margin < lim.margin:
        reason = f"top hypothesis leads its rivals by only {margin} (needs {lim.margin})"
    if reason:
        return Verdict(status="INCONCLUSIVE", ranked=ranked, margin=margin, reason=reason)
    return Verdict(
        status="ANSWER",
        ranked=ranked,
        margin=margin,
        reason="clear leader with sufficient evidence",
    )
