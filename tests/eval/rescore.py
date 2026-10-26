"""Re-score saved runs without re-running any investigation.

Usage: python -m eval.rescore results/<run> [--no-judge]
Reads each runs/<scenario>[+variant]-<system>-<n>/{report,board}.json plus the answer key, applies
the CURRENT judge and metrics, and writes rescored.jsonl and rescored.md next to the originals.
Use it after improving the judge or the metrics. To re-apply new scoring or grounding RULES to the
same recorded agent behaviour, replay the tapes instead (LLM_BACKEND=replay).
"""

import argparse
import asyncio
from pathlib import Path

from eval import variants
from eval.metrics import RunScore, scenario_table, score_run, summary_table
from incident.messages import Report
from incident.models import Dataset
from incident.sim.truth import Truth
from incident.state import Board

SCEN = Path(__file__).resolve().parents[2] / "scenarios"


async def rescore(results: Path, use_llm: bool) -> list[RunScore]:
    out: list[RunScore] = []
    for run in sorted((results / "runs").iterdir()):
        if not (run / "report.json").exists():
            continue
        name, system, n = run.name.rsplit("-", 2)
        scenario, _, variant = name.partition("+")
        truth = Truth.model_validate_json((SCEN / scenario / "truth.json").read_text("utf-8"))
        if variant:
            data = Dataset.model_validate_json((SCEN / scenario / "data.json").read_text("utf-8"))
            _, truth = variants.apply(variant, data, truth)
        report = Report.model_validate_json((run / "report.json").read_text("utf-8"))
        board = Board.model_validate_json((run / "board.json").read_text("utf-8"))
        out.append(await score_run(name, system, int(n), report, board, truth, use_llm))
    return out


async def main(results: Path, use_llm: bool) -> None:
    scores = await rescore(results, use_llm)
    (results / "rescored.jsonl").write_text(
        "".join(s.model_dump_json() + "\n" for s in scores), "utf-8"
    )
    text = (
        f"## Summary (re-scored)\n\n{summary_table(scores)}\n\n"
        f"## Per scenario\n\n{scenario_table(scores)}\n"
    )
    (results / "rescored.md").write_text(text, "utf-8")
    print(text)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("results", type=Path)
    p.add_argument("--no-judge", action="store_true")
    a = p.parse_args()
    asyncio.run(main(a.results, not a.no_judge))
