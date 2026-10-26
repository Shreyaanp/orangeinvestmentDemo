"""Tool invocation: validation, injected faults, per-call timeout, bounded retries."""

import asyncio
from typing import Any

from pydantic import ValidationError

from incident.models import ToolErrorInfo, ToolFault, ToolName, ToolOutcome
from incident.tools.registry import ALL_TOOLS, ToolSpec
from incident.tools.schemas import Result, ToolError, ToolTimeout, ToolUnavailable
from incident.tools.store import Store


def _degrade(r: Result[Any], f: ToolFault) -> Result[Any]:
    cap = f.max_results if f.max_results is not None else max(1, len(r.items) // 2)
    items = r.items[:cap]
    if f.kind == "truncate":
        if len(r.items) <= cap:
            return r
        note = f"result limit of {cap} reached; narrow the query"
        return r.model_copy(update={"items": items, "truncated": True, "note": note})
    note = "some data sources did not respond; results are incomplete"
    return r.model_copy(update={"items": items, "total": None, "partial": True, "note": note})


async def _attempt(store: Store, spec: ToolSpec, query: Any, timeout_s: float) -> Result[Any]:
    fault = store.begin_attempt(spec.name)
    if fault and fault.kind == "timeout":
        raise ToolTimeout(f"{spec.name} timed out")
    if fault and fault.kind == "unavailable":
        raise ToolUnavailable(f"{spec.name} is unavailable")
    try:
        result = await asyncio.wait_for(asyncio.to_thread(spec.run, store.data, query), timeout_s)
    except TimeoutError:
        raise ToolTimeout(f"{spec.name} exceeded {timeout_s}s") from None
    return _degrade(result, fault) if fault else result


def _failed(
    call_id: str, tool: ToolName, args: dict[str, Any], kind: Any, msg: str, retry: bool, n: int
) -> ToolOutcome:
    err = ToolErrorInfo(kind=kind, message=msg, retryable=retry)
    return ToolOutcome(call_id=call_id, tool=tool, args=args, ok=False, attempts=n, error=err)


async def invoke(
    store: Store,
    tool: ToolName,
    args: dict[str, Any],
    *,
    timeout_s: float = 5.0,
    retries: int = 2,
    backoff_s: float = 0.2,
    call_prefix: str = "tc",
) -> ToolOutcome:
    """Run one tool call. Retryable errors are retried up to `retries` times with backoff."""
    call_id, spec = store.new_call_id(call_prefix), ALL_TOOLS[tool]
    try:
        query = spec.input.model_validate(args)
    except ValidationError as e:
        return _failed(
            call_id, tool, args, "invalid_input", str(e.errors(include_url=False)), False, 0
        )
    for attempt in range(1, retries + 2):
        try:
            result = await _attempt(store, spec, query, timeout_s)
        except ToolError as e:
            if not e.retryable or attempt > retries:
                return _failed(call_id, tool, args, e.kind, str(e), e.retryable, attempt)
            await asyncio.sleep(backoff_s * 2 ** (attempt - 1))
            continue
        raw = result.model_dump_json()
        store.results[call_id] = raw
        return ToolOutcome(
            call_id=call_id, tool=tool, args=args, ok=True, attempts=attempt, result_json=raw,
            truncated=result.truncated, partial=result.partial,
        )  # fmt: skip
    raise AssertionError("unreachable: loop always returns")
