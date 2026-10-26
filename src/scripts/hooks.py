"""Claude Code hook entrypoints. Reads hook JSON on stdin; exit 2 blocks and tells Claude why."""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_VENV = ROOT / ".venv" / "Scripts" / "python.exe"
# Interpreter with dev tools: INCIDENT_PY, else ./.venv, else the current one.
PY = os.environ.get("INCIDENT_PY") or (str(_VENV) if _VENV.exists() else sys.executable)
# A real invocation at the start of the first line, optionally after `cd x &&`.
COMMIT_RE = re.compile(r"\s*(?:[^\n]*?(?:&&|;|\|\|)\s*)?git\s+(?:-C\s+\S+\s+)?commit\b")


def fail(msg: str) -> None:
    print(msg, file=sys.stderr)
    sys.exit(2)


def format_py(path: str) -> None:
    if not path.endswith(".py") or not Path(path).exists():
        return
    py = PY
    path = os.path.relpath(path, ROOT)  # relative so per-file-ignores match on Windows
    subprocess.run([py, "-m", "ruff", "format", path], capture_output=True, cwd=ROOT)
    r = subprocess.run(
        [py, "-m", "ruff", "check", "--fix", path], capture_output=True, text=True, cwd=ROOT
    )
    if "No module named ruff" in r.stderr:
        return
    if r.returncode == 1:
        fail(f"ruff found issues in {path}:\n{r.stdout[-1200:]}")


def protect_truth(path: str) -> None:
    if (
        re.search(r"scenarios[\\/](?:[^\\/]+[\\/])+truth\.json$", path)
        and os.environ.get("ALLOW_TRUTH_EDIT") != "1"
    ):
        fail(
            "Blocked: scenario ground truth is never edited to make a run pass (CLAUDE.md rule 3). "
            "Ask the user; they can set ALLOW_TRUTH_EDIT=1."
        )


def commit_gate(command: str) -> None:
    if not COMMIT_RE.match(command.split("\n")[0]):
        return
    r = subprocess.run([PY, "src/scripts/gate.py"], capture_output=True, text=True, cwd=ROOT)
    if r.returncode != 0:
        fail(f"Commit blocked by quality gate:\n{r.stdout[-2000:]}")


def main() -> None:
    event = json.load(sys.stdin)
    tool_input = event.get("tool_input", {})
    path = tool_input.get("file_path", "")
    match sys.argv[1]:
        case "format":
            format_py(path)
        case "protect":
            protect_truth(path)
        case "commit-gate":
            commit_gate(tool_input.get("command", ""))


if __name__ == "__main__":
    main()
