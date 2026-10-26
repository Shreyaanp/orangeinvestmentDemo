"""Deterministic grounding: a FACT must quote a real tool result; a claim must cite real evidence.

This checks that evidence exists and was quoted faithfully. It cannot check that a claim is a
sound inference from the quote; that is the Critic's job and the eval judge's.
"""

import json
import re
from collections.abc import Mapping

from incident.messages import Claim, Evidence, EvidenceDraft, Flag
from incident.models import Strict

COVERAGE = 0.9  # share of words in the excerpt that must appear in the source
ASSUMPTION_RELIABILITY = 0.3
PENALTY: dict[Flag, float] = {
    "partial": 0.6,
    "truncated": 0.8,
    "history": 0.5,
    "assumption": 1.0,
    "empty": 0.4,  # a filtered search that found nothing proves little: the filter may be wrong
}


class Grounded(Strict):
    ok: bool
    reason: str = ""
    reliability: float = 0.0
    flags: list[Flag] = []


def _tokens(text: str) -> list[str]:
    return re.findall(r"\d+(?:\.\d+)?|[a-z]{3,}", text.lower())


def _missing(excerpt: str, source: str) -> list[str]:
    have = set(_tokens(source))
    want = _tokens(excerpt)
    gone = [t for t in want if t not in have]
    numbers_gone = [t for t in gone if t[0].isdigit()]
    if numbers_gone or len(want) - len(gone) < COVERAGE * len(want):
        return gone or want
    return []


def _flags(raw: str) -> list[Flag]:
    body = json.loads(raw)
    flags: list[Flag] = []
    if body.get("partial"):
        flags.append("partial")
    if body.get("truncated"):
        flags.append("truncated")
    if not body.get("items"):
        flags.append("empty")
    items = body.get("items") or [{}]
    if isinstance(items[0], dict) and "root_cause" in items[0]:
        flags.append("history")
    return flags


def check_evidence(d: EvidenceDraft, results: Mapping[str, str]) -> Grounded:
    """results maps tool call id -> raw result json (Store.results)."""
    if d.kind == "ASSUMPTION":
        return Grounded(ok=True, reliability=ASSUMPTION_RELIABILITY, flags=["assumption"])
    if d.source_call_id is None or d.source_call_id not in results:
        return Grounded(ok=False, reason=f"FACT cites unknown call {d.source_call_id!r}")
    if not d.excerpt.strip():
        return Grounded(ok=False, reason="FACT needs a verbatim excerpt")
    raw = results[d.source_call_id]
    gone = _missing(d.excerpt, raw)
    if gone:
        return Grounded(ok=False, reason=f"excerpt not in {d.source_call_id}: {gone[:3]}")
    flags = _flags(raw)
    reliability = 1.0
    for f in flags:
        reliability *= PENALTY[f]
    return Grounded(ok=True, reliability=round(reliability, 3), flags=flags)


def clean_claims(claims: list[Claim], ledger: Mapping[str, Evidence]) -> tuple[list[Claim], int]:
    """Drop claims that cite nothing or cite evidence that does not exist."""
    kept = [c for c in claims if c.evidence_ids and all(i in ledger for i in c.evidence_ids)]
    return kept, len(claims) - len(kept)


def claim_kind(c: Claim, ledger: Mapping[str, Evidence]) -> str:
    """A claim is a FACT only if every piece of evidence it cites is a FACT."""
    return "FACT" if all(ledger[i].kind == "FACT" for i in c.evidence_ids) else "ASSUMPTION"
