"""Evaluation harness: run the multi-agent system and the single-agent baseline on scenarios.

Usage: python -m eval.run [--scenarios s01 s05 ...] [--systems multi baseline] [--runs 1]
       [--core-runs 3] [--backend claude_code|replay] [--record] [--no-judge] [--concurrency 3]
       [--variant shift|rename|shuffle|herring|drop] [--out NAME] [--resume] [--lean]
       [--memory loo|recurrence|misleading] [--catalogue scenarios/catalog/v1.json]
Results are appended to results/<out>/scores.jsonl as each run finishes. If the model account runs
out of quota the harness stops cleanly (nothing is scored from a quota failure); rerun the same
command with --resume to continue, on the same or another account (CLAUDE_CONFIG_DIR).
Only this package reads the answer keys.
"""

import argparse
import asyncio
import logging
import os
from datetime import datetime
from pathlib import Path

from eval import kb, variants
from eval.metrics import RunScore, failed_run, scenario_table, score_run, summary_table
from incident.agents.common import Outcome, guarded
from incident.baseline import investigate_baseline
from incident.hybrid import investigate_hybrid
from incident.knowledge import load
from incident.llm import LlmFactory
from incident.models import Dataset
from incident.orchestrator import investigate
from incident.protocol import QuotaError
from incident.sim.truth import Truth
from incident.state import Limits
from incident.tools.store import Store
from incident.trace import Trace

ROOT = Path(__file__).resolve().parents[2]
SCEN, TAPES = ROOT / "scenarios", ROOT / "tapes"
CORE = tuple(f"s{i:02d}_" for i in range(1, 13))
SYSTEMS = {"multi": investigate, "baseline": investigate_baseline, "hybrid": investigate_hybrid}


def pick(patterns: list[str], root: Path = SCEN) -> list[Path]:
    dirs = [d for d in sorted(root.iterdir()) if (d / "truth.json").exists()]
    return [d for d in dirs if not patterns or any(d.name.startswith(p) for p in patterns)]


def job_name(scn: Path, a: argparse.Namespace) -> str:
    return f"{scn.name}+{a.variant}" if a.variant else scn.name


async def run_job(scn: Path, system: str, run: int, a: argparse.Namespace, out: Path) -> RunScore:
    """Raises QuotaError if the model account is out of quota (never scored)."""
    truth = Truth.model_validate_json((scn / "truth.json").read_text("utf-8"))
    data = Dataset.model_validate_json((scn / "data.json").read_text("utf-8"))
    if a.variant:
        data, truth = variants.apply(a.variant, data, truth)
    name = job_name(scn, a)
    tapes = TAPES / a.tapes if a.tapes else TAPES / "lean" if a.lean else TAPES
    factory = LlmFactory(a.backend, tape=tapes / name / f"{system}-{run}.jsonl", record=a.record)
    run_dir = out / "runs" / f"{name}-{system}-{run}"
    call = SYSTEMS[system]
    trace = Trace(run_dir / "trace.jsonl")
    limits = Limits(lean=a.lean)
    memory = kb.build(scn.name, a.memory, [d.name for d in pick([])]) if a.memory else None
    cat = load(a.catalogue) if a.catalogue else None
    res, err = await guarded(
        call(
            Store(data), factory, limits=limits, trace=trace, run_dir=run_dir, memory=memory,
            incident_id=name, catalogue=cat,
        )
    )  # fmt: skip
    if not isinstance(res, Outcome):
        return failed_run(name, system, run, truth, err or "no result")
    (run_dir / "report.json").write_text(res.report.model_dump_json(indent=1), "utf-8")
    s = await score_run(name, system, run, res.report, res.board, truth, not a.no_judge)
    return kb.score_history(s, res.report, res.board, truth)


def load_done(out: Path) -> list[RunScore]:
    path = out / "scores.jsonl"
    if not path.exists():
        return []
    lines = path.read_text("utf-8").splitlines()
    return [RunScore.model_validate_json(ln) for ln in lines if ln]


async def main(a: argparse.Namespace) -> None:
    for noisy in ("google_adk", "google.adk", "google_genai"):
        logging.getLogger(noisy).setLevel(logging.CRITICAL)  # failures are contained and traced
    out = ROOT / "results" / (a.out or datetime.now().strftime("%Y%m%d-%H%M%S"))
    out.mkdir(parents=True, exist_ok=True)
    scores = load_done(out) if a.resume else []
    done = {(s.scenario, s.system, s.run) for s in scores}
    sem, stop = asyncio.Semaphore(a.concurrency), asyncio.Event()

    async def one(scn: Path, system: str, run: int) -> None:
        if stop.is_set() or (job_name(scn, a), system, run) in done:
            return
        async with sem:
            if stop.is_set():
                return
            try:
                s = await run_job(scn, system, run, a, out)
            except QuotaError as e:
                stop.set()
                print(f"QUOTA EXHAUSTED ({e}); stopping. Re-run with --resume to continue.")
                return
            with (out / "scores.jsonl").open("a", encoding="utf-8") as f:
                f.write(s.model_dump_json() + "\n")
            scores.append(s)
            print(f"{s.scenario:30s} {s.system:8s} run{run} {s.outcome:9s} ({s.status}) {s.top}")

    jobs = []
    for scn in pick(a.scenarios, a.root):
        runs = a.core_runs if scn.name.startswith(CORE) else a.runs
        jobs += [one(scn, sysname, r) for sysname in a.systems for r in range(1, runs + 1)]
    await asyncio.gather(*jobs)
    text = f"## Summary\n\n{summary_table(scores)}\n\n## Per scenario\n\n{scenario_table(scores)}\n"
    (out / "summary.md").write_text(text, "utf-8")
    note = "\nINCOMPLETE: quota ran out; rerun with --resume." if stop.is_set() else ""
    print("\n" + text + f"\nSaved to {out}{note}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--scenarios", nargs="*", default=[])
    p.add_argument("--systems", nargs="+", default=["multi", "baseline"], choices=list(SYSTEMS))
    p.add_argument("--runs", type=int, default=1)
    p.add_argument("--core-runs", type=int, default=1)
    p.add_argument("--backend", default=os.environ.get("LLM_BACKEND", "claude_code"))
    p.add_argument("--record", action="store_true")
    p.add_argument("--no-judge", action="store_true")
    p.add_argument("--variant", choices=variants.NAMES, default="")
    p.add_argument("--concurrency", type=int, default=3)
    p.add_argument("--out", default="")
    p.add_argument("--resume", action="store_true")
    p.add_argument(
        "--lean", action="store_true", help="efficiency profile (digest tools, compact ledger)"
    )
    p.add_argument("--memory", choices=kb.MODES, default="", help="seed incident memory")
    p.add_argument("--catalogue", type=Path, default=None, help="system catalogue JSON")
    p.add_argument("--tapes", default="", help="tape subfolder (keeps new tapes apart)")
    p.add_argument(
        "--root", type=Path, default=SCEN, help="scenario folder (e.g. scenarios/rcaeval)"
    )
    asyncio.run(main(p.parse_args()))
