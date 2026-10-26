"""HTTP API: start an investigation on a scenario, poll it, read its trace.

Auth: set API_KEY and send it as X-API-Key (open when unset, for local use only).
Backend: LLM_BACKEND=claude_code (live; needs CLAUDE_CODE_OAUTH_TOKEN when hosted) or replay
(serves recorded tapes from TAPES_DIR, no LLM needed). Runs are capped and time-limited.
"""

import asyncio
import os
import re
import uuid
from pathlib import Path
from typing import Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

from incident.agents.common import guarded
from incident.baseline import investigate_baseline
from incident.hybrid import investigate_hybrid
from incident.llm import LlmFactory
from incident.messages import Report
from incident.orchestrator import investigate
from incident.protocol import QuotaError
from incident.tools.store import Store
from incident.trace import Trace

ROOT = Path(os.environ.get("APP_DIR", Path(__file__).resolve().parents[2]))
SCENARIOS, TAPES, RUNS = ROOT / "scenarios", ROOT / "tapes", ROOT / "runs"
TAPE_DIRS = ("", "v2demo", "hybrid")  # recorded runs, searched in this order
MAX_CONCURRENT = int(os.environ.get("MAX_CONCURRENT_RUNS", "2"))
RUN_TIMEOUT_S = float(os.environ.get("RUN_TIMEOUT_S", "900"))
ID_RE = re.compile(r"^[a-z]\d{2}_[a-z0-9_]+$")  # a scenario folder name; no path characters

app = FastAPI(title="Incident investigator", version="1.0")
runs: dict[str, dict[str, Any]] = {}
_tasks: set[asyncio.Task[None]] = set()


class StartRequest(BaseModel):
    scenario_id: str
    system: Literal["multi", "baseline", "hybrid"] = "multi"


def check_key(x_api_key: str | None = Header(default=None)) -> None:
    expected = os.environ.get("API_KEY")
    if expected and x_api_key != expected:
        raise HTTPException(401, "invalid or missing X-API-Key")


def scenario_ids() -> list[str]:
    if not SCENARIOS.exists():
        return []
    return sorted(d.name for d in SCENARIOS.iterdir() if (d / "data.json").exists())


async def _execute(run_id: str, req: StartRequest) -> None:
    rec = runs[run_id]
    backend = os.environ.get("LLM_BACKEND", "claude_code")
    tapes = [TAPES / sub / req.scenario_id / f"{req.system}-1.jsonl" for sub in TAPE_DIRS]
    tape = next((t for t in tapes if t.exists()), tapes[0])
    factory = LlmFactory(backend, tape=tape if backend == "replay" else None)
    store = Store.load(SCENARIOS / req.scenario_id)
    run_dir = RUNS / run_id
    trace = Trace(run_dir / "trace.jsonl")
    call = {"multi": investigate, "baseline": investigate_baseline, "hybrid": investigate_hybrid}[
        req.system
    ]
    work = call(store, factory, trace=trace, run_dir=run_dir)
    try:
        out, err = await guarded(asyncio.wait_for(work, RUN_TIMEOUT_S))
    except QuotaError as e:
        out, err = None, f"model quota exhausted: {e}"
    rec["trace"] = trace
    if out is None:
        rec.update(status="error", error=err or "run failed")
    else:
        rec.update(status="done", report=out.report)


@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    return {
        "ok": True,
        "backend": os.environ.get("LLM_BACKEND", "claude_code"),
        "scenarios": len(scenario_ids()),
    }


@app.get("/scenarios", dependencies=[Depends(check_key)])
async def list_scenarios() -> list[str]:
    return scenario_ids()


@app.post("/investigations", status_code=202, dependencies=[Depends(check_key)])
async def start(req: StartRequest) -> dict[str, str]:
    if not ID_RE.match(req.scenario_id) or req.scenario_id not in scenario_ids():
        raise HTTPException(404, "unknown scenario")
    if sum(r["status"] == "running" for r in runs.values()) >= MAX_CONCURRENT:
        raise HTTPException(429, "too many investigations running; retry shortly")
    run_id = uuid.uuid4().hex[:12]
    runs[run_id] = {"status": "running", "scenario_id": req.scenario_id, "system": req.system}
    task = asyncio.create_task(_execute(run_id, req))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return {"run_id": run_id, "status": "running"}


def _get(run_id: str) -> dict[str, Any]:
    if run_id not in runs:
        raise HTTPException(404, "unknown run")
    return runs[run_id]


@app.get("/investigations/{run_id}", dependencies=[Depends(check_key)])
async def status(run_id: str) -> dict[str, Any]:
    rec = _get(run_id)
    report: Report | None = rec.get("report")
    return {
        "run_id": run_id,
        "status": rec["status"],
        "scenario_id": rec["scenario_id"],
        "system": rec["system"],
        "error": rec.get("error"),
        "report": report.model_dump() if report else None,
    }


@app.get("/investigations/{run_id}/trace", dependencies=[Depends(check_key)])
async def trace(run_id: str) -> list[dict[str, Any]]:
    t: Trace | None = _get(run_id).get("trace")
    return t.events if t else []
