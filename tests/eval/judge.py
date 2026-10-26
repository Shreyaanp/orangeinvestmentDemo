"""Cause matching: does a hypothesis identify the same root cause as the answer key?

The component must match exactly (deterministic). The mechanism is then judged by a small LLM with
a fixed rubric. To keep a noisy judge from deciding outcomes: the model must write its reasoning
BEFORE the verdict, three independent judgments are taken and the majority wins, and verdicts are
cached on disk so reruns are free and stable.
"""

import asyncio
import hashlib
import json
from pathlib import Path

from incident.llm import FAST, claude_complete
from incident.protocol import parse_protocol

CACHE = Path(__file__).resolve().parents[2] / "results" / "judge_cache.jsonl"
VOTES = 3
RUBRIC = (
    "You grade incident root-cause analysis. Decide whether the PROPOSED cause identifies the same "
    "failing component AND the same underlying failure as the TRUE cause. Wording and level of "
    "detail do not matter: a more or less specific description of the same failure, or one "
    "that includes the immediate trigger or consequences described in TRUE, IS the same. It is NOT "
    "the same if it blames a different mechanism, a downstream symptom or bystander change as the "
    "root cause, if it says the mechanism is unknown, or if it names a different component. The "
    "TRUE label is a short slug; use the description. Reason first, then give the verdict. "
    'Reply {"final":{"why":"<your reasoning>","same":true|false}}.'
)
RUBRIC_ID = hashlib.sha256(RUBRIC.encode()).hexdigest()[:8]


def build_prompt(
    true_component: str,
    true_cause: str,
    true_description: str,
    component: str,
    cause_type: str,
    statement: str,
) -> str:
    return (
        f"TRUE: component={true_component}, label={true_cause}\n"
        f"TRUE description: {true_description or '(none given)'}\n"
        f"PROPOSED: component={component}, cause={cause_type}\n"
        f"PROPOSED statement: {statement}"
    )


def _cached() -> dict[str, bool]:
    if not CACHE.exists():
        return {}
    rows = (json.loads(ln) for ln in CACHE.read_text("utf-8").splitlines() if ln.strip())
    return {r["key"]: r["same"] for r in rows}


async def _vote(prompt: str) -> bool:
    text, _, _, _ = await claude_complete(RUBRIC, prompt, *FAST)
    return bool(parse_protocol(text)["final"]["same"])


async def same_cause(
    true_component: str,
    true_cause: str,
    component: str,
    cause_type: str,
    statement: str,
    use_llm: bool = True,
    true_description: str = "",
) -> bool:
    if component.strip().lower() != true_component.strip().lower():
        return False
    if not use_llm:  # offline mode: component-only matching, reported as such
        return True
    prompt = build_prompt(
        true_component, true_cause, true_description, component, cause_type, statement
    )
    key = hashlib.sha256(f"{RUBRIC_ID}|{prompt}".encode()).hexdigest()[:16]
    known = _cached()
    if key in known:
        return known[key]
    votes = await asyncio.gather(*(_vote(prompt) for _ in range(VOTES)))
    same = sum(votes) * 2 > VOTES
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    with CACHE.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"key": key, "same": same, "votes": votes}) + "\n")
    return same
