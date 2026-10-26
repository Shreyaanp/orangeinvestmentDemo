"""Freeze live reports as golden files next to their recorded tapes.

Usage: python scripts/bless_goldens.py results/<run>
Each results/<run>/runs/<scenario>-<system>-<n>/report.json is copied to
tapes/<scenario>/<system>-<n>.report.json. tests/golden then requires that replaying the tape
reproduces that report exactly, so any behaviour change in orchestration, grounding or scoring
shows up as a diff instead of silently changing results. Bless only after reviewing the run.
"""

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main(results: Path) -> None:
    blessed = 0
    for run in sorted((results / "runs").iterdir()):
        scenario, system, n = run.name.rsplit("-", 2)
        tape = ROOT / "tapes" / scenario / f"{system}-{n}.jsonl"
        if tape.exists() and (run / "report.json").exists():
            shutil.copy(run / "report.json", tape.with_suffix(".report.json"))
            if (run / "board.json").exists():
                shutil.copy(run / "board.json", tape.with_suffix(".board.json"))
            blessed += 1
    print(f"blessed {blessed} golden reports from {results}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
