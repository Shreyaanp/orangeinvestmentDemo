"""One investigation, narrated: what each agent is doing as it happens, what it concluded, and a
page with every prompt, reply, parameter and score.

  python -m eval.demo                          # a01, replayed from its tape: no key, no tokens
  python -m eval.demo s05_poison_message       # any scenario that has a recorded tape
  python -m eval.demo --pace 0.3               # replay slowly enough to narrate
  python -m eval.demo a03_poison_buttons --live   # a real run (Claude Code login)

Writes results/demo/<scenario>/ (trace, board, report, prompts.jsonl, walkthrough.html).
"""

import argparse
import asyncio
import html
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

from eval.metrics import score_run
from incident.agents.common import Outcome, guarded
from incident.hybrid import investigate_hybrid
from incident.llm import ROLE_MODEL, LlmFactory
from incident.models import Dataset
from incident.orchestrator import investigate
from incident.sim.truth import Truth
from incident.state import Board, Limits
from incident.tools.store import Store
from incident.trace import Trace

ROOT = Path(__file__).resolve().parents[2]
HOMES = (ROOT / "scenarios", ROOT / "scenarios" / "rcaeval")
RUN = {"multi": investigate, "hybrid": investigate_hybrid}
TAPES = ("v2demo", "hybrid", "exp_rca_default", "", "fresh")  # tape folders searched in this order


class Narrated(Trace):
    """A trace that also prints each step as one readable line, optionally paced for watching."""

    pace = 0.0

    def emit(self, kind: str, **f: Any) -> None:
        super().emit(kind, **f)
        time.sleep(self.pace)  # replay is instant; a pause per step makes it watchable
        t = f"{self.events[-1]['t']:7.1f}s"
        if kind == "tool":
            args = {k: v for k, v in f["args"].items() if v not in (None, [], "")}
            mark = "" if f["ok"] else f"  FAILED: {f['error']}"
            print(f"{t}  tool  {f['call']:<6} {f['tool']:<18} {json.dumps(args)[:90]}{mark}")
        elif kind == "investigated":
            print(f"{t}  INVESTIGATOR (one agent, full context): {f['evidence']} grounded facts, "
                  f"{f['hypotheses']} hypotheses")  # fmt: skip
        elif kind == "plan":
            print(f"{t}  PLANNER split the ticket into {f['tasks']} tasks")
        elif kind == "task":
            print(f"{t}  {f.get('agent', '')} finished {f['id']}: {f.get('evidence', 0)} facts")
        elif kind == "reasoning":
            n = f.get("hypotheses", 0)
            what = f"proposed {n} hypotheses" if n else "re-weighed the hypotheses on new evidence"
            print(f"{t}  REASONING {what}")
        elif kind == "round":
            verdict = "approves" if f["approve"] else "objects, asks for more checks"
            print(f"{t}  CRITIC {verdict} (round {f['n']}, leader margin {f['margin']})")
        elif kind == "final":
            print(f"{t}  REPORT {f['status']}")


def _find(sid: str) -> Path:
    for home in HOMES:
        if (home / sid / "data.json").exists():
            return home / sid
    sys.exit(f"no scenario {sid!r} under scenarios/ or scenarios/rcaeval/")


def _tape(sid: str, system: str) -> Path:
    for sub in TAPES:
        path = ROOT / "tapes" / sub / sid / f"{system}-1.jsonl"
        if path.exists() and path.stat().st_size:
            return path
    sys.exit(f"no recorded run for {sid}; use --live, or pick one with a tape under tapes/")


def _rule(title: str) -> None:
    print(f"\n{'=' * 8} {title} {'=' * max(4, 70 - len(title))}")


def _world(data: Dataset) -> None:
    _rule("1. THE WORLD (everything the agents can query)")
    print(f"services ({len(data.topology.services)}): {', '.join(data.topology.services)}")
    print(
        f"{data.minutes} minutes of data: {len(data.logs):,} log lines, "
        f"{sum(len(v) for v in data.metrics.values())} metric series, "
        f"{len(data.changes)} changes, {len(data.history)} past incidents"
    )
    if data.conversations:
        print(
            f"{len(data.conversations):,} WhatsApp messages traced end to end, "
            f"{len(data.code_changes)} git commits with diffs"
        )
    for c in data.changes:
        print(f"  {c.ts:%H:%M}  {c.kind:<9} {c.service:<14} {c.ref:<12} {c.note[:60]}")
    _rule("2. THE TICKET")
    print(data.incident.text)


def _reveal(truth: Truth, score: Any) -> None:
    _rule("5. THE HIDDEN ANSWER KEY (the agents never saw this)")
    for f in truth.faults:
        print(f"{f.component} / {f.cause_type}: {f.description}")
    print(f"trap: {truth.trap}")
    _rule("6. THE SCORE")
    print(f"{score.outcome.upper()}: top hypothesis {score.top}")
    print(
        f"decisive evidence cited {score.decisive_recall:.0%}, "
        f"hallucinated evidence {score.hallucination_rate:.0%}; "
        f"{score.llm_calls} model calls, {score.tool_calls} tool calls, {score.tokens:,} tokens"
    )


def _story(b: Board) -> None:
    print("\nWHAT THE AGENTS DID")
    for t in b.tasks.values():
        print(f"  {t.id} {t.agent}: {t.goal[:150]}")
    print("\nHYPOTHESES")
    for h in b.hypotheses.values():
        print(f"  {h.id} [{h.status}] {h.statement[:200]}")
        print(f"      for: {', '.join(h.supporting)}  against: {', '.join(h.contradicting) or '-'}")
    if b.challenges:
        print("\nCRITIC OBJECTIONS")
        for c in b.challenges.values():
            print(f"  {c.target} {c.kind}: {c.objection[:220]}")


def _table(head: list[str], rows: list[list[Any]]) -> str:
    cells = "".join(f"<th>{html.escape(h)}</th>" for h in head)
    body = "".join(
        "<tr>" + "".join(f"<td>{html.escape(str(c))}</td>" for c in r) + "</tr>" for r in rows
    )
    return f"<table><tr>{cells}</tr>{body}</table>"


def _page(sid: str, data: Dataset, truth: Truth, res: Outcome, score: Any, calls: Path) -> str:
    e = html.escape
    rep, b = res.report, res.board
    rows = [json.loads(x) for x in calls.read_text("utf-8").splitlines()] if calls.exists() else []
    parts = [
        f"<h1>{e(sid)}: one investigation, start to end</h1>",
        f"<p><b>{e(score.outcome.upper())}</b> ({e(score.status)}, top {e(score.top)}): "
        f"{score.llm_calls} LLM calls, {score.tool_calls} tool calls, {score.tokens:,} tokens.</p>",
        f"<h2>Ticket</h2><p>{e(data.incident.text)}</p>",
        "<h2>Answer key (hidden from the agents)</h2>",
        "".join(f"<p>{e(f.component)} / {e(f.cause_type)}: {e(f.description)}</p>"
                for f in truth.faults) or "<p>No cause can be established.</p>",
        f"<p><b>Trap:</b> {e(truth.trap)}</p>",
        "<h2>Models</h2>",
        _table(["role", "model", "effort"], [[r, m, x or "default"]
                                             for r, (m, x) in ROLE_MODEL.items()]),
        "<h2>Limits</h2>",
        _table(["limit", "value"], [[k, v] for k, v in b.limits.model_dump().items()]),
        "<h2>Timeline</h2>",
        _table(["t (s)", "event", "detail"], [
            [ev["t"], ev["kind"], json.dumps({k: v for k, v in ev.items()
                                              if k not in ("seq", "t", "kind")})[:300]]
            for ev in res.trace.events]),
        "<h2>Tasks</h2>",
        _table(["id", "agent", "goal"], [[t.id, t.agent, t.goal] for t in b.tasks.values()]),
        "<h2>LLM calls (exact prompts)</h2>",
        _table(["#", "agent", "model", "effort", "tokens in", "tokens out"],
               [[i + 1, r["key"], r["model"], r["effort"], r["tin"], r["tout"]]
                for i, r in enumerate(rows)]),
        *[f"<details><summary>#{i + 1} {e(r['key'])}</summary><h4>System</h4>"
          f"<pre>{e(r['system'])}</pre><h4>Prompt</h4><pre>{e(r['prompt'])}</pre>"
          f"<h4>Reply</h4><pre>{e(r['reply'])}</pre></details>" for i, r in enumerate(rows)],
        "<h2>Evidence ledger</h2>",
        _table(["id", "kind", "service", "claim", "from call"],
               [[k, v.kind, v.service, v.claim, v.source_call_id] for k, v in b.evidence.items()]),
        f"<h2>Report: {e(rep.status)}</h2><p>{e(rep.summary)}</p>",
        _table(["rank", "hypothesis", "cause", "confidence"],
               [[h.rank, h.statement, f"{h.component}/{h.cause_type}", h.confidence]
                for h in rep.hypotheses]),
        "<h2>Score against the answer key</h2>",
        _table(["metric", "value"], [[k, v] for k, v in score.model_dump().items()]),
    ]  # fmt: skip
    css = (
        "body{font:14px/1.5 system-ui,sans-serif;max-width:1100px;margin:24px auto;padding:0 16px;"
        "background:#fff;color:#1a1a1a}table{border-collapse:collapse;width:100%;font-size:13px}"
        "td,th{border:1px solid #ddd;padding:4px 6px;text-align:left;vertical-align:top}"
        "pre{white-space:pre-wrap;background:#f6f6f6;padding:8px;max-height:480px;overflow:auto}"
        "@media (prefers-color-scheme:dark){body{background:#161616;color:#e6e6e6}"
        "td,th{border-color:#3a3a3a}pre{background:#202020}}"
    )
    return (
        "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
        f"<title>{e(sid)} walkthrough</title><style>{css}</style>" + "".join(parts)
    )


async def main(a: argparse.Namespace) -> None:
    logging.getLogger("google_adk").setLevel(logging.CRITICAL)
    folder = _find(a.scenario)
    data = Dataset.model_validate_json((folder / "data.json").read_text("utf-8"))
    truth = Truth.model_validate_json((folder / "truth.json").read_text("utf-8"))
    out = ROOT / "results" / "demo" / (a.scenario + ("" if a.system == "multi" else f"-{a.system}"))
    out.mkdir(parents=True, exist_ok=True)
    for f in ("trace.jsonl", "prompts.jsonl"):
        (out / f).unlink(missing_ok=True)
    os.environ["LLM_DUMP"] = str(out / "prompts.jsonl")
    Narrated.pace = 0.0 if a.live else a.pace
    backend = "claude_code" if a.live else "replay"
    factory = LlmFactory(backend, tape=None if a.live else _tape(a.scenario, a.system))
    _world(data)
    _rule(f"3. THE AGENTS AT WORK ({'live' if a.live else 'replay of a recorded live run'})")
    res, err = await guarded(
        RUN[a.system](Store(data), factory, limits=Limits(), trace=Narrated(out / "trace.jsonl"),
                    run_dir=out, incident_id=a.scenario)
    )  # fmt: skip
    if not isinstance(res, Outcome):
        sys.exit(f"investigation failed: {err}")
    (out / "report.json").write_text(res.report.model_dump_json(indent=1), "utf-8")
    score = await score_run(a.scenario, a.system, 1, res.report, res.board, truth, False)
    _story(res.board)
    _rule(f"4. THE ANSWER: {res.report.status}")
    print(f"why: {res.report.status_reason}\n\n{res.report.summary}")
    _reveal(truth, score)
    page = out / "walkthrough.html"
    page.write_text(_page(a.scenario, data, truth, res, score, out / "prompts.jsonl"), "utf-8")
    print(f"Every prompt, reply and parameter: {page}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("scenario", nargs="?", default="a01_broker_timeout")
    p.add_argument("--live", action="store_true", help="real model calls instead of the tape")
    p.add_argument("--system", choices=sorted(RUN), default="multi", help="multi-agent or hybrid")
    p.add_argument("--pace", type=float, default=0.0, help="seconds to pause per step (replay)")
    asyncio.run(main(p.parse_args()))
