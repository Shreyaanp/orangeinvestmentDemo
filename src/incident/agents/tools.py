"""Expose the investigation tools to ADK agents, with budget and evidence-gap accounting."""

import json
from typing import Any

from google.adk.tools.base_tool import BaseTool
from google.genai import types

from incident.agents.common import Ctx
from incident.models import ToolName, ToolOutcome
from incident.tools.guard import invoke
from incident.tools.registry import ALL_TOOLS, ToolSpec


def render(out: ToolOutcome) -> dict[str, Any]:
    """The compact, citable view of a tool result that the model sees."""
    if not out.ok or out.result_json is None:
        err = out.error.model_dump() if out.error else {}
        return {"call_id": out.call_id, "ok": False, "error": err, "attempts": out.attempts}
    body = json.loads(out.result_json)
    if out.tool == "query_logs":
        urls = sorted({i["url"] for i in body["items"] if i.get("url")})
        if urls:  # provenance: where a human can verify these lines (absent for simulated data)
            body["sources"] = urls[:3]
        body["items"] = [
            f"{i['ts']} {i['level']} {i['service']}: {i['msg']}" for i in body["items"]
        ]
    return {"call_id": out.call_id, "ok": True, **body}


class IncidentTool(BaseTool):
    def __init__(self, spec: ToolSpec, ctx: Ctx, prefix: str) -> None:
        super().__init__(name=spec.name, description=spec.description)
        self.spec, self.ctx, self.prefix = spec, ctx, prefix

    def _get_declaration(self) -> types.FunctionDeclaration:
        schema = self.spec.input.model_json_schema()
        return types.FunctionDeclaration(
            name=self.name, description=self.description, parameters_json_schema=schema
        )

    async def run_async(self, *, args: dict[str, Any], tool_context: Any) -> dict[str, Any]:
        c = self.ctx
        if (why := c.board.budget_exceeded()) is not None:
            return {
                "ok": False,
                "error": f"budget exhausted ({why}): stop and report what you have",
            }
        memo_key = f"{self.spec.name}:{json.dumps(args, sort_keys=True, default=str)}"
        if c.board.limits.lean and memo_key in c.memo:
            return {**c.memo[memo_key], "cached": True}
        out = await invoke(c.store, self.spec.name, args, call_prefix=self.prefix)
        c.board.usage.tool_calls += 1 if out.attempts else 0  # invalid input is free
        c.board.usage.tool_attempts += out.attempts
        self._gaps(out, args)
        c.trace.emit(
            "tool",
            call=out.call_id,
            tool=out.tool,
            args=args,
            ok=out.ok,
            attempts=out.attempts,
            partial=out.partial,
            truncated=out.truncated,
            error=out.error.kind if out.error else None,
        )
        shown = render(out)
        if c.board.limits.lean and out.ok:
            c.memo[memo_key] = shown
        return shown

    def _gaps(self, out: ToolOutcome, args: dict[str, Any]) -> None:
        """A failed or partial call is a structural gap, resolved by a later clean call."""
        key = (out.tool, args.get("service"))
        board, keys = self.ctx.board, self.ctx.gap_keys
        if not out.ok or out.partial:
            what = out.error.kind if out.error else "partial result"
            keys[key] = board.add_gap(f"{out.tool}({args.get('service')}): {what}", out.call_id).id
        elif key in keys:
            gap_id = keys.pop(key)
            for g in board.gaps:
                g.resolved = g.resolved or g.id == gap_id


def tools_for(names: list[ToolName], ctx: Ctx, prefix: str) -> list[BaseTool]:
    return [IncidentTool(ALL_TOOLS[n], ctx, prefix) for n in names]
