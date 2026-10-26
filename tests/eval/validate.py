"""Scenario validator: each scenario must be solvable through the tools, or deliberately not.

Usage: python -m eval.validate [scenario_id ...]
"""

import asyncio
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from incident.models import Dataset, ToolName
from incident.sim.truth import Selector, Truth
from incident.tools.guard import invoke
from incident.tools.store import Store

SCEN = Path(__file__).resolve().parents[2] / "scenarios"
ALL_KINDS = ["deploy", "config", "migration", "flag"]


def _oracle_call(sel: Selector) -> tuple[ToolName, dict[str, Any]]:
    if sel.kind == "log":
        args = {
            "service": sel.service,
            "level": sel.level,
            "contains": sel.contains,
            "start": sel.start.isoformat(),
            "end": sel.end.isoformat(),
        }
        return "query_logs", args
    if sel.kind == "change":
        return "get_changes", {"service": sel.service, "kinds": ALL_KINDS}
    if sel.kind == "code":
        return "get_code_change", {"service": sel.service, "path": sel.contains}
    if sel.kind == "conversation":
        window = {"start": sel.start.isoformat(), "end": sel.end.isoformat(), "limit": 20}
        return "conversation_trace", {
            **window,
            **({"tool_failed": True} if sel.failed_tool else {}),
        }
    return "query_metrics", {"service": sel.service, "metric": sel.metric}


def _hit(sel: Selector, items: list[dict[str, Any]]) -> bool:
    if sel.kind == "log":
        return bool(items)
    if sel.kind == "change":
        return any(sel.contains in c["ref"] for c in items)
    if sel.kind == "code":
        return bool(items)
    if sel.kind == "conversation":
        return any(sel.contains in json.dumps(c) for c in items)
    assert sel.min_value is not None
    return any((i["stats"]["max"] or 0) >= sel.min_value for i in items)


async def reachable(data: Dataset, sel: Selector) -> bool:
    """Can a well-informed investigator surface this evidence with the real tools (incl. faults)?"""
    tool, args = _oracle_call(sel)
    out = await invoke(Store(data), tool, args, retries=3, backoff_s=0)
    if not out.ok or out.result_json is None:
        return False
    return _hit(sel, json.loads(out.result_json)["items"])


async def validate(scenario_dir: Path) -> list[str]:
    data = Dataset.model_validate_json((scenario_dir / "data.json").read_text("utf-8"))
    truth = Truth.model_validate_json((scenario_dir / "truth.json").read_text("utf-8"))
    issues: list[str] = []
    if not truth.faults:
        issues.append("no primary fault")
    if not truth.trap:
        issues.append("trap description missing")
    for tf in data.tool_faults:
        if tf.kind in ("truncate", "partial") and tf.max_results is None:
            issues.append(f"{tf.tool} {tf.kind} fault needs max_results")
    for fault in truth.faults:
        if not fault.decisive:
            issues.append(f"{fault.id}: no decisive selector")
        for sel in fault.decisive:
            if await reachable(data, sel) != truth.answerable:
                want = "reachable" if truth.answerable else "absent"
                issues.append(
                    f"{fault.id}: {sel.kind} evidence {sel.contains or sel.metric!r} not {want}"
                )
    return issues


async def main(only: list[str]) -> int:
    dirs = [d for d in sorted(SCEN.iterdir()) if (d / "truth.json").exists()]
    dirs = [d for d in dirs if not only or d.name in only]
    status: Counter[str] = Counter()
    bad = 0
    for d in dirs:
        issues = await validate(d)
        truth = Truth.model_validate_json((d / "truth.json").read_text("utf-8"))
        status[truth.expected_status] += 1
        bad += bool(issues)
        print(f"{'FAIL' if issues else 'ok  '} {d.name}: {truth.trap}")
        for i in issues:
            print(f"       - {i}")
    print(f"{len(dirs)} scenarios, expected outcomes: {dict(status)}, {bad} failing")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
