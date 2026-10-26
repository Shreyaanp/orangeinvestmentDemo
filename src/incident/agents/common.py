"""Shared plumbing: run one ADK LlmAgent, parse its JSON answer into a model, retry once."""

import asyncio
import time
from collections.abc import Awaitable
from dataclasses import dataclass, field
from pathlib import Path

from google.adk.agents import LlmAgent
from google.adk.agents.run_config import RunConfig
from google.adk.runners import InMemoryRunner
from google.adk.tools.base_tool import BaseTool
from google.genai import types
from pydantic import BaseModel

from incident.knowledge import Catalogue, context_text
from incident.llm import RUN_KEY, LlmFactory, Role
from incident.memory import Memory
from incident.messages import PastIncident, Report
from incident.protocol import LlmError, QuotaError
from incident.state import Board
from incident.tools.store import Store
from incident.trace import Trace

PROMPTS = Path(__file__).parent / "prompts"


@dataclass
class Ctx:
    board: Board
    store: Store
    factory: LlmFactory
    trace: Trace
    run_dir: Path | None = None
    gap_keys: dict[tuple[str, str | None], str] = field(default_factory=dict)
    memo: dict[str, dict] = field(default_factory=dict)  # type: ignore[type-arg]
    timeout_s: float = 300.0
    max_llm_calls: int = 30
    t0: float = field(default_factory=time.monotonic)


def prompt_text(name: str, lean: bool = False) -> str:
    text = (PROMPTS / f"{name}.md").read_text(encoding="utf-8")
    extra = PROMPTS / f"lean_{name}.md"
    return text + extra.read_text(encoding="utf-8") if lean and extra.exists() else text


async def run_agent(
    ctx: Ctx,
    *,
    name: str,
    role: Role,
    instruction: str,
    prompt: str,
    tools: list[BaseTool],
    key: str,
) -> str:
    """One isolated ADK agent run. `instruction` is a callable so ADK does not template it."""
    agent = LlmAgent(
        name=name,
        model=ctx.factory.llm(role),
        instruction=lambda _ctx: instruction,
        tools=list(tools),
        disallow_transfer_to_parent=True,
        disallow_transfer_to_peers=True,
    )
    runner = InMemoryRunner(agent=agent, app_name="incident")
    session = await runner.session_service.create_session(app_name="incident", user_id="inv")
    message = types.Content(role="user", parts=[types.Part(text=prompt)])
    config = RunConfig(max_llm_calls=ctx.max_llm_calls)
    token, final = RUN_KEY.set(key), ""
    try:
        async for ev in runner.run_async(
            user_id="inv", session_id=session.id, new_message=message, run_config=config
        ):
            if ev.usage_metadata:
                use = ctx.board.usage
                use.llm_calls += 1
                use.tokens_in += ev.usage_metadata.prompt_token_count or 0
                use.tokens_out += ev.usage_metadata.candidates_token_count or 0
                served = ev.model_version or "unknown"
                use.models[served] = use.models.get(served, 0) + 1
            if ev.is_final_response() and ev.content and ev.content.parts:
                final = "".join(p.text or "" for p in ev.content.parts)
    finally:
        RUN_KEY.reset(token)
    return final


async def run_json[T: BaseModel](
    ctx: Ctx,
    *,
    name: str,
    role: Role,
    instruction: str,
    prompt: str,
    model: type[T],
    key: str,
    tools: list[BaseTool] | None = None,
) -> T:
    """Run an agent and validate its answer; on invalid output ask once more with the error."""
    problem = ""
    for attempt in (0, 1):
        ask = prompt if not attempt else f"{prompt}\n\nYour previous answer was invalid: {problem}"
        run = run_agent(
            ctx,
            name=name,
            role=role,
            instruction=instruction,
            prompt=ask,
            tools=tools or [],
            key=key if not attempt else f"{key}/repair",
        )
        try:
            text = await asyncio.wait_for(run, ctx.timeout_s)
        except TimeoutError as e:
            raise LlmError(f"{name} timed out after {ctx.timeout_s}s") from e
        try:
            return model.model_validate_json(text)
        except ValueError as e:
            problem = str(e)[:400]
    raise LlmError(f"{name} produced no valid {model.__name__}: {problem}")


@dataclass
class Outcome:
    report: Report
    board: Board
    trace: Trace


async def guarded[T](aw: Awaitable[T]) -> tuple[T | None, str | None]:
    """Isolation boundary: one agent's failure must never end the investigation."""
    try:
        return await aw, None
    except QuotaError:
        raise
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"[:300]


def save_board(ctx: Ctx) -> None:
    if ctx.run_dir:
        ctx.run_dir.mkdir(parents=True, exist_ok=True)
        (ctx.run_dir / "board.json").write_text(ctx.board.model_dump_json(indent=1), "utf-8")


def recall(memory: Memory | None, store: Store, incident_id: str) -> list[PastIncident]:
    """Add similar past incidents, labelled with provenance, to the history agents can search."""
    if memory is None:
        return []
    data = store.data
    mentioned = [s for s in data.topology.services if s in data.incident.text]
    past = memory.similar_past(data.incident.text, mentioned, exclude={incident_id})
    if past:
        hints = [memory.hint(p) for p in past]
        store.data = data.model_copy(update={"history": [*data.history, *hints]})
    return past


def prime(board: Board, catalogue: Catalogue | None, past: list[PastIncident]) -> None:
    """Give the board what the team knows before looking at telemetry."""
    board.past, board.context = past, context_text(catalogue, past)


def known(board: Board) -> str:
    return f"\n\n{board.context}\n" if board.context else ""


def remember(
    memory: Memory | None, store: Store, board: Board, report: Report, incident_id: str
) -> None:
    """Store this investigation as the agent's own, unconfirmed conclusion."""
    if memory is None:
        return
    seen = sorted({e.service for e in board.evidence.values() if e.service})
    memory.record(
        incident_id=incident_id,
        text=board.incident_text,
        when=store.data.incident.reported_at,
        services=seen,
        report=report,
        topology=store.data.topology,
        changes=store.data.changes,
    )
