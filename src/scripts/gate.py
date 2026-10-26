"""Quality gate: `gate.py` (full), `--ci` (no tests), `--strict` (matrix fully covered)."""

import ast
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "incident"
MAX_FILE, MAX_FUNC, MAX_LOC, MAX_SIM_LOC, MAX_ADAPTER_LOC, MAX_OPTIONAL_LOC = (
    250,
    40,
    2500,
    450,
    450,
    400,
)
MAX_RETRIEVAL_LOC = 150  # opt-in hybrid retrieval (retrieval.py), kept out of the core budget
OPTIONAL = {
    "memory.py",
    "digest.py",
}  # opt-in subsystems: incident memory and the lean digest tools
# Application-level suite: its event simulator and the runtime records/tools that read it.
MAX_APP_SIM_LOC, MAX_APP_LOC = 750, 300
APP_RUNTIME = {"app_models.py", "funnel.py", "conversations.py", "code.py"}
FORBIDDEN_IN_SRC = ("truth.json", "ground_truth")
BUDGET = {
    "runtime": MAX_LOC,
    "sim": MAX_SIM_LOC,
    "app_sim": MAX_APP_SIM_LOC,
    "app": MAX_APP_LOC,
    "adapters": MAX_ADAPTER_LOC,
    "optional": MAX_OPTIONAL_LOC,
    "retrieval": MAX_RETRIEVAL_LOC,
}


def py_files(base: Path) -> list[Path]:
    return sorted(base.rglob("*.py")) if base.exists() else []


def file_problems(f: Path, text: str) -> list[str]:
    rel, lines = f.relative_to(ROOT), text.splitlines()
    errs = [f"{rel}: {len(lines)} lines > {MAX_FILE}"] if len(lines) > MAX_FILE else []
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            n = (node.end_lineno or node.lineno) - node.lineno + 1
            if n > MAX_FUNC:
                errs.append(f"{rel}:{node.lineno} function {node.name} {n} lines > {MAX_FUNC}")
        if isinstance(node, ast.ExceptHandler) and node.type is None:
            errs.append(f"{rel}:{node.lineno} bare except")
    return errs


def _group(parts: tuple[str, ...], name: str) -> str:
    if "sim" in parts:
        return "app_sim" if "app" in parts else "sim"
    if "adapters" in parts:
        return "adapters"
    if name in OPTIONAL:
        return "optional"
    if name == "retrieval.py":
        return "retrieval"
    return "app" if name in APP_RUNTIME else "runtime"


def check_size_and_bans() -> list[str]:
    errs: list[str] = []
    loc = dict.fromkeys(BUDGET, 0)
    for f in py_files(SRC):
        text = f.read_text(encoding="utf-8")
        group = _group(f.relative_to(SRC).parts, f.name)
        loc[group] += sum(
            1 for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")
        )
        errs += file_problems(f, text)
    errs += [f"{g} is {n} LOC > budget {BUDGET[g]}" for g, n in loc.items() if n > BUDGET[g]]
    print("  info: " + ", ".join(f"{g} {n}/{BUDGET[g]} LOC" for g, n in loc.items()))
    return errs


def check_truth_isolation() -> list[str]:
    """Runtime code must not reference ground truth or any scenario id."""
    scen = ROOT / "scenarios"
    ids = [d.name for d in scen.iterdir() if (d / "truth.json").exists()] if scen.exists() else []
    errs: list[str] = []
    for f in py_files(SRC):
        text = f.read_text(encoding="utf-8")
        for bad in (*FORBIDDEN_IN_SRC, *ids):
            if re.search(rf"\b{re.escape(bad)}\b", text):
                errs.append(
                    f"{f.relative_to(ROOT)}: references '{bad}' (ground truth / scenario id)"
                )
    return errs


def check_matrix(strict: bool) -> list[str]:
    rows = re.findall(r"^\| (R\d+) \|", (ROOT / "tests" / "REQUIREMENTS.md").read_text(), re.M)
    tests = py_files(ROOT / "tests")
    covered = set(
        re.findall(r"covers:\s*((?:R\d+[, ]*)+)", "\n".join(t.read_text() for t in tests))
    )
    covered = {r for grp in covered for r in re.findall(r"R\d+", grp)}
    missing = [r for r in rows if r not in covered]
    if missing and not strict:
        print(f"  info: {len(missing)}/{len(rows)} requirements untested: {', '.join(missing)}")
        return []
    return [f"requirement {r} has no test with '# covers: {r}'" for r in missing]


def run(name: str, cmd: list[str]) -> list[str]:
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if r.returncode == 0:
        return []
    return [f"{name} failed:\n{(r.stdout + r.stderr).strip()[-1500:]}"]


def tool_checks(ci: bool) -> list[str]:
    py = sys.executable
    targets = [p for p in ("src", "tests/eval", "tests/mockworld") if (ROOT / p).exists()]
    errs = run("ruff check", [py, "-m", "ruff", "check", *targets])
    errs += run("ruff format", [py, "-m", "ruff", "format", "--check", *targets])
    if SRC.exists():
        errs += run("mypy", [py, "-m", "mypy", *targets])  # src/scripts is excluded in pyproject
        lint = "from importlinter.cli import lint_imports_command as m; m()"
        errs += run("import-linter", [py, "-c", lint])
    if not ci and (ROOT / "tests").exists():
        errs += run("pytest", [py, "-m", "pytest", "-q"])
    return errs


def main() -> int:
    ci, strict = "--ci" in sys.argv, "--strict" in sys.argv
    errs = [*check_size_and_bans(), *check_truth_isolation(), *check_matrix(strict and not ci)]
    errs += tool_checks(ci)
    for e in errs:
        print(f"FAIL {e}")
    print("GATE PASSED" if not errs else f"GATE FAILED ({len(errs)})")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
