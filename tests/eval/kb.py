"""Seed incident memory for the live knowledge-base test from REAL saved agent reports.

Each past incident is another scenario's saved investigation (its report, as the agents wrote it),
with the on-call verdict taken from that scenario's answer key: correct -> CONFIRMED, wrong ->
REJECTED with the actual cause, abstained -> left as an INCONCLUSIVE conclusion. Modes:
  loo         memory holds every OTHER scenario; nothing about the query's own fault
  recurrence  loo + the query's own earlier investigation (run the query with --variant shift or
              rename, so it is a recurrence and not the identical report)
  misleading  loo + a CONFIRMED look-alike: the query's own incident text, but the conclusion and
              fix of a scenario with a different cause (stored first, so ties go to it)
"""

from datetime import UTC, datetime
from pathlib import Path

from eval.metrics import RunScore
from incident.memory import Memory
from incident.messages import Report
from incident.models import Dataset
from incident.sim.truth import Truth
from incident.state import Board

ROOT = Path(__file__).resolve().parents[2]
SAVED = ("acc1a", "acc1b", "full2", "full1")  # newest first
MODES = ("loo", "recurrence", "misleading")
WHEN = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
PREV, LOOKALIKE = "previous-occurrence", "lookalike"


def saved_report(sid: str) -> Report | None:
    for d in SAVED:
        for system in ("multi", "baseline"):
            f = ROOT / "results" / d / "runs" / f"{sid}-{system}-1" / "report.json"
            if f.exists():
                return Report.model_validate_json(f.read_text("utf-8"))
    return None


def _primary(truth: Truth) -> tuple[str, str]:
    f = next(f for f in truth.faults if f.role == "primary")
    return f.component, f.description


def _load(sid: str) -> tuple[Dataset, Truth]:
    d = ROOT / "scenarios" / sid
    data = Dataset.model_validate_json((d / "data.json").read_text("utf-8"))
    return data, Truth.model_validate_json((d / "truth.json").read_text("utf-8"))


def _add(m: Memory, iid: str, data: Dataset, report: Report, truth: Truth) -> None:
    services = [s for s in data.topology.services if s in data.incident.text]
    top = report.hypotheses[0].component if report.hypotheses else None
    m.record(
        incident_id=iid, text=data.incident.text, when=WHEN,
        services=sorted({*services, *([top] if top else [])}), report=report,
        topology=data.topology,
    )  # fmt: skip
    if report.status != "ANSWER" or not truth.answerable:
        return
    component, actual = _primary(truth)
    m.confirm(iid, top == component, actual=None if top == component else actual)


def build(query: str, mode: str, scenarios: list[str]) -> Memory:
    m = Memory()
    q_data, q_truth = _load(query)
    if mode == "misleading":
        q_comp, _ = _primary(q_truth)
        for sid in (s for s in scenarios if s != query):
            rep, (_, truth) = saved_report(sid), _load(sid)
            comp = _primary(truth)[0]
            right = rep and rep.status == "ANSWER" and rep.hypotheses[0].component == comp
            if right and comp != q_comp and rep:
                _add(m, LOOKALIKE, q_data, rep, truth)  # confirmed: it was right THERE
                break
    for sid in scenarios:
        rep = saved_report(sid)
        if sid != query and rep:
            data, truth = _load(sid)
            _add(m, sid, data, rep, truth)
    own = saved_report(query)
    if mode == "recurrence" and own:
        _add(m, PREV, q_data, own, q_truth)
    return m


def score_history(s: RunScore, report: Report, board: Board, truth: Truth) -> RunScore:
    """A history fix is right when the past incident it came from had the true component."""
    used = [a for a in report.actions if a.source == "history"]
    comp = {p.id: p.component for p in board.past}
    true_comp = _primary(truth)[0]
    ids = [a.text.removeprefix("[from history: ").split("]")[0] for a in used]
    right = all(comp.get(i) == true_comp for i in ids) if ids else None
    return s.model_copy(
        update={
            "recalled": len(board.past),
            "history_actions": len(used),
            "history_fix_right": right,
        }
    )
