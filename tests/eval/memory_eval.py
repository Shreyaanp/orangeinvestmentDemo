"""Offline evaluation of incident memory retrieval (no LLM, no network unless fastembed downloads).

Usage: python -m eval.memory_eval [--modes keyword,fake,hybrid] [--json OUT]

For each scenario Q, memory holds the other scenarios' conclusions (taken from their answer keys,
stored as unconfirmed agent conclusions) plus ONE earlier occurrence of Q's own fault, written as:
  shift       the same report with every clock time moved
  rename      the same report with every service renamed
  postmortem  every stored incident (the distractors too) is its written-up cause, not its
              symptom report, as when memory is seeded from postmortems: the semantic gap
The query is Q's incident text and the services it mentions (as `recall` does at runtime). A hit is
the earlier occurrence. Reported: recall@1, recall@3, MRR (rank beyond k=3 counts as a miss).

Misleading memory: a past incident whose text is Q's own report but whose recorded cause is a
different scenario's. Without feedback it is expected to outrank the true occurrence (retrieval
cannot know); the checks are that it stays a labelled hint, that on-call feedback (true occurrence
confirmed, lookalike rejected) restores the order, and that quoting a hint through
search_incidents is graded as history evidence (reliability halved), never as a full fact.
"""

import argparse
import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from eval import variants
from incident.grounding import check_evidence
from incident.memory import Memory
from incident.messages import Action, EvidenceDraft, RankedHypothesis, Report, RunStats
from incident.models import Dataset, HistoryItem
from incident.sim.truth import Truth, TruthFault
from incident.tools.guard import invoke
from incident.tools.store import Store

SCEN = Path(__file__).resolve().parents[2] / "scenarios"
WHEN = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
PREV = "previous-occurrence"
LOOKALIKE = "lookalike"
K = 3
LABELS = ("[CONFIRMED", "[agent-concluded, UNCONFIRMED", "[agent conclusion was REJECTED", "[prev")


@dataclass
class Case:
    sid: str
    data: Dataset
    truth: Truth

    @property
    def fault(self) -> TruthFault:
        return next(f for f in self.truth.faults if f.role == "primary")

    def services(self, data: Dataset | None = None) -> list[str]:
        d = data or self.data
        return [s for s in d.topology.services if s in d.incident.text]


def load_cases() -> list[Case]:
    out = []
    for d in sorted(p for p in SCEN.iterdir() if (p / "truth.json").exists()):
        data = Dataset.model_validate_json((d / "data.json").read_text("utf-8"))
        truth = Truth.model_validate_json((d / "truth.json").read_text("utf-8"))
        out.append(Case(d.name, data, truth))
    return out


def report_for(f: TruthFault) -> Report:
    top = RankedHypothesis(
        rank=1, hypothesis_id="H1", statement=f.description, component=f.component,
        cause_type=f.cause_type, score=3.0, confidence=0.7, label="high", supporting=[],
        contradicting=[],
    )  # fmt: skip
    act = Action(text="see postmortem", rationale="-", evidence_ids=["E-001"], priority="immediate")
    return Report(
        status="ANSWER", status_reason="", summary="", hypotheses=[top], facts=[], assumptions=[],
        unresolved=[], actions=[act], stats=RunStats(),
    )  # fmt: skip


def store(m: Memory, iid: str, text: str, services: list[str], f: TruthFault, c: Case) -> None:
    """services: those the report mentions; the concluded component is added, as evidence would."""
    m.record(
        incident_id=iid, text=text, when=WHEN, services=sorted({*services, f.component}),
        report=report_for(f), topology=c.data.topology,
    )  # fmt: skip


def memory_for(q: Case, cases: list[Case], mode: str, postmortem: bool = False) -> Memory:
    m = Memory(retrieval=mode)
    for c in cases:
        if c.sid != q.sid:
            text = c.fault.description if postmortem else c.data.incident.text
            store(m, c.sid, text, c.services(), c.fault, c)
    return m


def add_previous(m: Memory, q: Case, variant: str) -> None:
    if variant == "postmortem":
        store(m, PREV, q.fault.description, q.services(), q.fault, q)
        return
    data, truth = variants.apply(variant, q.data, q.truth)
    fault = next(f for f in truth.faults if f.role == "primary")
    store(m, PREV, data.incident.text, q.services(data), fault, q)


def rank_of(hints: list[HistoryItem], iid: str) -> int | None:
    return next((i + 1 for i, h in enumerate(hints) if h.id == iid), None)


def recall_metrics(cases: list[Case], mode: str, variant: str) -> dict[str, float]:
    ranks = []
    for q in cases:
        m = memory_for(q, cases, mode, postmortem=variant == "postmortem")
        add_previous(m, q, variant)
        ranks.append(rank_of(m.similar(q.data.incident.text, q.services(), k=K), PREV))
    n = len(ranks)
    return {
        "recall@1": sum(r == 1 for r in ranks) / n,
        "recall@3": sum(r is not None for r in ranks) / n,
        "mrr": sum(1 / r for r in ranks if r) / n,
    }


def other_fault(q: Case, cases: list[Case]) -> TruthFault:
    return next(c.fault for c in cases if c.fault.cause_type != q.fault.cause_type)


async def hint_is_weak_evidence(q: Case, hints: list[HistoryItem]) -> bool:
    """Quote a memory hint through search_incidents; grounding must flag it as history."""
    st = Store(q.data.model_copy(update={"history": hints, "tool_faults": []}))
    out = await invoke(st, "search_incidents", {"query": hints[0].summary[:200]})
    if not out.ok:
        return False
    item = json.loads(out.result_json or "{}")["items"][0]
    d = EvidenceDraft(
        kind="FACT", claim="c", excerpt=item["root_cause"], source_call_id=out.call_id
    )
    g = check_evidence(d, st.results)
    return g.ok and "history" in g.flags and g.reliability < 1.0


def misleading(cases: list[Case], mode: str) -> dict[str, float]:
    above = restored = labelled = rejected_shown = weak = 0
    for q in cases:
        m = memory_for(q, cases, mode)
        # Same text and services as Q, another cause; stored first so ties go to it (worst case).
        m.record(
            incident_id=LOOKALIKE, text=q.data.incident.text, when=WHEN,
            services=sorted({*q.services(), q.fault.component}),
            report=report_for(other_fault(q, cases)), topology=q.data.topology,
        )  # fmt: skip
        add_previous(m, q, "shift")
        hints = m.similar(q.data.incident.text, q.services(), k=K)
        r_prev, r_look = rank_of(hints, PREV), rank_of(hints, LOOKALIKE)
        above += r_look is not None and (r_prev is None or r_look < r_prev)
        labelled += all(h.source == "memory" and h.root_cause.startswith(LABELS) for h in hints)
        weak += asyncio.run(hint_is_weak_evidence(q, hints))
        m.confirm(PREV, True)
        m.confirm(LOOKALIKE, False, actual=q.fault.description)
        hints = m.similar(q.data.incident.text, q.services(), k=K)
        restored += rank_of(hints, PREV) == 1
        look = next((h for h in hints if h.id == LOOKALIKE), None)
        rejected_shown += look is None or "REJECTED" in look.root_cause
    n = len(cases)
    return {
        "lookalike_above_true": above / n,
        "all_hints_labelled": labelled / n,
        "hint_graded_as_history": weak / n,
        "true_first_after_feedback": restored / n,
        "lookalike_marked_rejected": rejected_shown / n,
    }


def evaluate(modes: list[str]) -> dict[str, dict[str, dict[str, float]]]:
    cases = load_cases()
    out: dict[str, dict[str, dict[str, float]]] = {}
    for mode in modes:
        out[mode] = {v: recall_metrics(cases, mode, v) for v in ("shift", "rename", "postmortem")}
        out[mode]["misleading"] = misleading(cases, mode)
    return out


def print_table(res: dict[str, dict[str, dict[str, float]]]) -> None:
    print(f"{'mode':<8} {'variant':<11} {'R@1':>5} {'R@3':>5} {'MRR':>5}")
    for mode, by in res.items():
        for v, m in by.items():
            if v != "misleading":
                print(
                    f"{mode:<8} {v:<11} {m['recall@1']:5.2f} {m['recall@3']:5.2f} {m['mrr']:5.2f}"
                )
    for mode, by in res.items():
        print(
            f"{mode} misleading: " + ", ".join(f"{k}={v:.2f}" for k, v in by["misleading"].items())
        )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--modes", default="keyword,fake", help="keyword,fake,hybrid (hybrid=fastembed)"
    )
    ap.add_argument("--json", type=Path, help="also write the numbers here")
    a = ap.parse_args()
    res = evaluate(a.modes.split(","))
    print_table(res)
    if a.json:
        a.json.write_text(json.dumps(res, indent=1), "utf-8")


if __name__ == "__main__":
    main()
