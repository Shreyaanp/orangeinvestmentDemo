"""LLM backends behind one tool-calling protocol.

claude_code: the user's Claude Code login via the Agent SDK (live). Optionally records a tape.
replay:      serves a recorded tape, so a whole investigation replays offline and deterministically.
fake:        a scripted function, for unit tests.
The model replies with one JSON object: {"tool_calls": [...]} or {"final": ...}.
"""

import asyncio
import json
import os
import re
import time
from collections import Counter
from collections.abc import AsyncGenerator, Callable
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Literal

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKError,
    ResultMessage,
    TextBlock,
    query,
)
from google.adk.models import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from incident.protocol import (
    PROTOCOL,
    RETRY_NOTE,
    LlmError,
    QuotaError,
    content_of,
    parse_protocol,
    render,
)

RUN_KEY: ContextVar[str] = ContextVar("run_key", default="adhoc")
Role = Literal[
    "planner", "observability", "dependency", "reasoning", "critic", "reporting", "baseline"
]
Effort = Literal["low", "medium", "high", "xhigh", "max"]
# Sonnet and Opus both at medium effort: Sonnet for planning and tool loops; Opus for judgement
# (reasoning, critic, reporting, and the single-agent baseline, which does its own judgement).
# Pinned model ids, not aliases, so a run never silently changes model. Override with
# LLM_MODEL_<ROLE>/LLM_EFFORT_<ROLE>.
FAST: tuple[str, Effort | None] = ("claude-sonnet-5-5", "medium")
STRONG: tuple[str, Effort | None] = ("claude-opus-5-5", "medium")
ROLE_MODEL: dict[str, tuple[str, Effort | None]] = {
    "planner": FAST, "observability": FAST, "dependency": FAST,
    "reasoning": STRONG, "critic": STRONG, "reporting": STRONG, "baseline": STRONG,
}  # fmt: skip
QUOTA = re.compile(r"hit your (session|usage|weekly)|usage limit|session limit", re.I)
TIMEOUT_S = float(os.environ.get("LLM_TIMEOUT_S", "150"))
_SEM: list[asyncio.Semaphore] = []


class Tape:
    """Recorded model replies keyed by (run key, call number within that run)."""

    def __init__(self, path: Path | None = None, record: bool = False) -> None:
        self.path, self.record_mode = path, record and path is not None
        self.rows: dict[tuple[str, int], dict[str, Any]] = {}
        self.count: Counter[str] = Counter()
        if path is None:
            return
        if record:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("", encoding="utf-8")
        elif path.exists():
            for line in path.read_text("utf-8").splitlines():
                row = json.loads(line)
                self.rows[(row["key"], row["n"])] = row

    def next_n(self, key: str) -> int:
        self.count[key] += 1
        return self.count[key]

    def get(self, key: str, n: int) -> dict[str, Any]:
        if (key, n) not in self.rows:
            raise LlmError(f"no recorded reply for {key}#{n}: re-record the tape")
        return self.rows[(key, n)]

    def put(self, key: str, n: int, text: str, tin: int, tout: int, model: str) -> None:
        if self.path is None:
            return
        row = {"key": key, "n": n, "text": text, "tin": tin, "tout": tout, "model": model}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")


def claude_options(system: str, model: str, effort: Effort | None = None) -> ClaudeAgentOptions:
    """Model-only session: no built-in tools, no user settings, and NO MCP connectors.

    Without strict_mcp_config the account's connected apps (mail, docs, ...) are exposed to the
    model and add ~30k tokens of tool definitions to every call.
    """
    return ClaudeAgentOptions(
        tools=[],
        system_prompt=system,
        max_turns=1,
        setting_sources=[],
        model=model,
        effort=effort,
        mcp_servers={},
        strict_mcp_config=True,
    )


async def claude_complete(
    system: str, prompt: str, model: str, effort: Effort | None = None
) -> tuple[str, int, int, str]:
    """Returns text, tokens in, tokens out, and the model id that actually answered."""
    if not _SEM:
        _SEM.append(asyncio.Semaphore(int(os.environ.get("LLM_CONCURRENCY", "6"))))
    opts = claude_options(system, model, effort)
    text, tin, tout, served = "", 0, 0, model
    async with _SEM[0]:
        async for m in query(prompt=prompt, options=opts):
            if isinstance(m, AssistantMessage):
                text += "".join(b.text for b in m.content if isinstance(b, TextBlock))
                served = m.model or served
            elif isinstance(m, ResultMessage):
                u = m.usage or {}
                tin = sum(
                    u.get(k, 0)
                    for k in (
                        "input_tokens",
                        "cache_read_input_tokens",
                        "cache_creation_input_tokens",
                    )
                )
                tout = u.get("output_tokens", 0)
    return text, tin, tout, served


class ProtocolLlm(BaseLlm):
    model: str = FAST[0]
    effort: Effort | None = None
    backend: Literal["claude_code", "replay", "fake"] = "claude_code"
    tape: Any = None
    script: Any = None  # fake backend: Callable[[str, int, str, str], str]

    async def _complete(
        self, system: str, prompt: str, key: str, n: int
    ) -> tuple[str, int, int, str]:
        if self.backend == "replay":
            row = self.tape.get(key, n)
            return row["text"], row["tin"], row["tout"], row.get("model", "unrecorded")
        if self.backend == "fake":
            fake: Callable[[str, int, str, str], str] = self.script
            return fake(key, n, system, prompt), 10, 5, self.model
        for attempt in range(3):
            try:
                call = claude_complete(system, prompt, self.model, self.effort)
                return await asyncio.wait_for(call, TIMEOUT_S)
            except (ClaudeSDKError, TimeoutError, OSError) as e:
                if QUOTA.search(str(e)):
                    raise QuotaError(f"claude_code quota exhausted: {e}") from e
                if attempt == 2:
                    raise LlmError(f"claude_code call failed: {e}") from e
                await asyncio.sleep(2.0 * (attempt + 1))
        raise AssertionError("unreachable")

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse]:
        system = PROTOCOL + "\n\n" + str(llm_request.config.system_instruction or "")
        prompt = render(llm_request)
        key = RUN_KEY.get()
        n = self.tape.next_n(key)
        tin = tout = 0
        began = time.monotonic()
        for attempt in (0, 1):
            text, i, o, served = await self._complete(
                system, prompt + (RETRY_NOTE if attempt else ""), key, n
            )
            tin, tout = tin + i, tout + o
            try:
                obj = parse_protocol(text)
                break
            except LlmError:
                if attempt:
                    raise
        if self.backend == "claude_code" and self.tape.record_mode:
            self.tape.put(key, n, text, tin, tout, served)
        if dump := os.environ.get("LLM_DUMP"):  # opt-in audit: exact prompt, params, timing
            row = {"key": key, "n": n, "model": self.model, "served": served,
                   "effort": self.effort, "backend": self.backend, "timeout_s": TIMEOUT_S,
                   "ms": round((time.monotonic() - began) * 1000), "tin": tin, "tout": tout,
                   "system": system, "prompt": prompt, "reply": text}  # fmt: skip
            with Path(dump).open("a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
        usage = types.GenerateContentResponseUsageMetadata(
            prompt_token_count=tin, candidates_token_count=tout, total_token_count=tin + tout
        )
        yield LlmResponse(content=content_of(obj), usage_metadata=usage, model_version=served)


class LlmFactory:
    """Builds the model for each agent role. One factory (and one tape) per investigation."""

    def __init__(
        self,
        backend: str | None = None,
        tape: Path | None = None,
        record: bool = False,
        script: Callable[[str, int, str, str], str] | None = None,
    ) -> None:
        self.backend: Any = backend or os.environ.get("LLM_BACKEND", "claude_code")
        if self.backend == "api":
            raise LlmError("LLM_BACKEND=api is not implemented; use claude_code, replay or fake")
        self.tape = Tape(tape, record)  # always present: it also numbers calls per run key
        self.script = script

    def llm(self, role: Role) -> ProtocolLlm:
        model, effort = ROLE_MODEL[role]
        model = os.environ.get(f"LLM_MODEL_{role.upper()}") or model
        effort = os.environ.get(f"LLM_EFFORT_{role.upper()}") or effort  # type: ignore[assignment]
        return ProtocolLlm(
            model=model, effort=effort, backend=self.backend, tape=self.tape, script=self.script
        )
