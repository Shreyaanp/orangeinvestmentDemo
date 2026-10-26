"""Metamorphic variants of a scenario. A system that reasons from the data is unaffected by the
first four; a system that memorised scenarios, or guesses, is not. The fifth removes the decisive
evidence, after which a well-calibrated system must not claim an answer.

  shift      move every timestamp by a constant
  rename     give every service a new name
  shuffle    scramble log order within each minute
  herring    add an unrelated deploy shortly before onset
  drop       delete the decisive evidence (expected outcome becomes INCONCLUSIVE)
"""

import random
import re
from datetime import timedelta

from incident.app_models import CodeChange, Conversation
from incident.models import Change, Dataset, LogLine
from incident.sim.truth import Selector, Truth

SHIFT = timedelta(hours=7, minutes=13)
NAMES = ("shift", "rename", "shuffle", "herring", "drop")
CLOCK = re.compile(r"\b(\d{2}):(\d{2})\b")


def _shift_text(text: str) -> str:
    def move(m: re.Match[str]) -> str:
        t = (int(m.group(1)) * 60 + int(m.group(2)) + int(SHIFT.total_seconds() // 60)) % 1440
        return f"{t // 60:02d}:{t % 60:02d}"

    return CLOCK.sub(move, text)


def _shift(data: Dataset, truth: Truth) -> tuple[Dataset, Truth]:
    d = data.model_copy(deep=True)
    d.start += SHIFT
    d.incident.reported_at += SHIFT
    d.incident.text = _shift_text(d.incident.text)
    for ln in d.logs:
        ln.ts += SHIFT
    for c in d.changes:
        c.ts += SHIFT
    for conv in d.conversations:
        conv.received_at += SHIFT
        for st in conv.stages:
            st.ts += SHIFT
    for code in d.code_changes:
        code.merged_at += SHIFT
    t = truth.model_copy(deep=True)
    for f in t.faults:
        f.onset += SHIFT
        for s in f.decisive:
            s.start, s.end = s.start + SHIFT, s.end + SHIFT
    return d, t


def _rename(data: Dataset, truth: Truth) -> tuple[Dataset, Truth]:
    names = sorted(data.topology.services, key=len, reverse=True)
    d_text, t_text = data.model_dump_json(), truth.model_dump_json()
    for n in names:
        pat = re.compile(rf"(?<![\w-]){re.escape(n)}(?!\w|-[A-Za-z])")
        d_text, t_text = pat.sub(f"{n}-prod", d_text), pat.sub(f"{n}-prod", t_text)
    return Dataset.model_validate_json(d_text), Truth.model_validate_json(t_text)


def _shuffle(data: Dataset, truth: Truth) -> tuple[Dataset, Truth]:
    rng = random.Random(7)
    buckets: dict[int, list[LogLine]] = {}
    for ln in data.logs:
        buckets.setdefault(int((ln.ts - data.start).total_seconds() // 60), []).append(ln)
    logs: list[LogLine] = []
    for minute in sorted(buckets):
        rng.shuffle(buckets[minute])
        logs += buckets[minute]
    return data.model_copy(update={"logs": logs}), truth


def _herring(data: Dataset, truth: Truth) -> tuple[Dataset, Truth]:
    culprits = {f.component for f in truth.faults}
    linked = {e.callee for e in data.topology.edges if e.caller in culprits}
    linked |= {e.caller for e in data.topology.edges if e.callee in culprits}
    pool = [s for s in sorted(data.topology.services) if s not in culprits | linked]
    onset = min(f.onset for f in truth.faults)
    deploy = Change(
        ts=onset - timedelta(minutes=8),
        kind="deploy",
        service=pool[0],
        ref=f"{pool[0]}-99999",
        note="dependency bump",
    )
    changes = sorted([*data.changes, deploy], key=lambda c: c.ts)
    return data.model_copy(update={"changes": changes}), truth


def _drop(data: Dataset, truth: Truth) -> tuple[Dataset, Truth]:
    sels = [s for f in truth.faults for s in f.decisive]
    logs = [ln for ln in data.logs if not any(_is_log(s, ln) for s in sels)]
    changes = [c for c in data.changes if not any(_is_change(s, c) for s in sels)]
    metrics = {svc: {k: list(v) for k, v in ms.items()} for svc, ms in data.metrics.items()}
    for s in sels:
        if s.kind == "metric" and s.metric:
            metrics[s.service][s.metric] = [None] * len(metrics[s.service][s.metric])
    convs = [c for c in data.conversations if not any(_is_conversation(s, c) for s in sels)]
    code = [c for c in data.code_changes if not any(_is_code(s, c) for s in sels)]
    d = data.model_copy(
        update={
            "logs": logs,
            "changes": changes,
            "metrics": metrics,
            "conversations": convs,
            "code_changes": code,
        }
    )
    t = truth.model_copy(update={"answerable": False, "expected_status": "INCONCLUSIVE"})
    return d, t


def _is_log(s: Selector, ln: LogLine) -> bool:
    return (
        s.kind == "log"
        and ln.service == s.service
        and s.contains.lower() in ln.msg.lower()
        and s.start <= ln.ts < s.end
    )


def _is_change(s: Selector, c: Change) -> bool:
    return s.kind == "change" and c.service == s.service and s.contains in c.ref


def _is_conversation(s: Selector, c: Conversation) -> bool:
    failed = any(not t.ok for t in c.tool_calls)
    return (
        s.kind == "conversation"
        and (failed or not s.failed_tool)
        and s.contains in c.model_dump_json()
        and s.start <= c.received_at < s.end
    )


def _is_code(s: Selector, c: CodeChange) -> bool:
    return (
        s.kind == "code" and c.service == s.service and any(s.contains in f.path for f in c.files)
    )


def apply(name: str, data: Dataset, truth: Truth) -> tuple[Dataset, Truth]:
    fns = {
        "shift": _shift,
        "rename": _rename,
        "shuffle": _shuffle,
        "herring": _herring,
        "drop": _drop,
    }
    return fns[name](data, truth)
