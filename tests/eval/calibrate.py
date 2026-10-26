"""Calibrate the decision thresholds offline on saved final boards (no LLM, no re-run).

Usage:
  python -m eval.calibrate results/<run> [--only s01 s02 ...]            sweep a small grid
  python -m eval.calibrate results/<run> --params min_confidence=0.35,margin=0.2   score one setting

The same thresholds apply to BOTH systems (they share the scoring code). The protocol that keeps
this honest: fit on one set of scenarios, write the chosen values down, then score scenarios the fit
never saw. Component-only matching is used (no judge), so results are free and reproducible.
Caveat: the investigation flow stays as recorded; only the final ANSWER/INCONCLUSIVE decision moves.
"""

import argparse
import asyncio
import itertools
from pathlib import Path

from eval.metrics import SCORE, classify
from incident import scoring
from incident.report import assemble
from incident.sim.truth import Truth
from incident.state import Board, Limits

SCEN = Path(__file__).resolve().parents[2] / "scenarios"
GRID = {
    "min_confidence": [0.3, 0.35, 0.4, 0.45],
    "margin": [0.1, 0.15, 0.2, 0.25],
    "contra_weight": [1.0, 1.25, 1.5],
    "contra_limit": [0.5, 0.75, 1.0, 99.0],
}


def load(results: Path, only: list[str]) -> list[tuple[str, str, Board, Truth]]:
    runs = []
    for run in sorted((results / "runs").iterdir()):
        name, system, _ = run.name.rsplit("-", 2)
        if "+" in name or (only and not any(name.startswith(p) for p in only)):
            continue
        if not (run / "board.json").exists():
            continue
        truth = Truth.model_validate_json((SCEN / name / "truth.json").read_text("utf-8"))
        runs.append(
            (
                name,
                system,
                Board.model_validate_json((run / "board.json").read_text("utf-8")),
                truth,
            )
        )
    return runs


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


async def evaluate(
    runs: list[tuple[str, str, Board, Truth]], params: dict[str, float]
) -> dict[str, float]:
    out: dict[str, list[float]] = {"multi": [], "baseline": []}
    wrong = abstained = 0
    for _, system, board, truth in runs:
        b = board.model_copy(update={"limits": Limits(**{**board.limits.model_dump(), **params})})
        outcome = await classify(assemble(b, scoring.verdict(b), None), truth, False)
        out[system].append(SCORE[outcome])
        wrong += outcome == "wrong"
        abstained += outcome == "abstained"
    n = max(1, sum(map(len, out.values())))
    return {
        "score": sum(sum(v) for v in out.values()) / n,
        "multi": _mean(out["multi"]),
        "baseline": _mean(out["baseline"]),
        "wrong": wrong,
        "abstained": abstained,
    }


def fmt(params: dict[str, float], r: dict[str, float]) -> str:
    p = " ".join(f"{k}={v}" for k, v in params.items())
    return (
        f"score={r['score']:+.3f} multi={r['multi']:+.3f} baseline={r['baseline']:+.3f} "
        f"wrong={r['wrong']:.0f} abstained={r['abstained']:.0f} | {p}"
    )


async def main(results: Path, only: list[str], params: str) -> None:
    runs = load(results, only)
    print(f"{len(runs)} saved runs from {results}")
    default = Limits().model_dump()
    if params:
        chosen = {k: float(v) for k, v in (kv.split("=") for kv in params.split(","))}
        print(fmt(chosen, await evaluate(runs, chosen)))
        return
    print("default  ", fmt({k: default[k] for k in GRID}, await evaluate(runs, {})))
    rows = []
    for combo in itertools.product(*GRID.values()):
        p = dict(zip(GRID, combo, strict=True))
        # distance from the defaults, in grid steps: prefer the smallest change that helps
        dist = sum(
            abs(
                GRID[k].index(v)
                - min(range(len(GRID[k])), key=lambda i: abs(GRID[k][i] - default[k]))
            )
            for k, v in p.items()
        )
        rows.append((await evaluate(runs, p), p, dist))
    rows.sort(key=lambda x: (-x[0]["score"], x[0]["wrong"], x[2]))
    print("best by score (ties: fewest wrong, then closest to defaults):")
    for r, p, d in rows[:8]:
        print(" ", fmt(p, r), f"| steps from default={d}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("results", type=Path)
    ap.add_argument("--only", nargs="*", default=[])
    ap.add_argument("--params", default="")
    a = ap.parse_args()
    asyncio.run(main(a.results, a.only, a.params))
