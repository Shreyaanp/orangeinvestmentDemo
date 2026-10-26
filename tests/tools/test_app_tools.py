"""message_funnel, conversation_trace and get_code_change, and when they are offered."""

import json
from pathlib import Path

import pytest

from incident.models import Dataset
from incident.tools.guard import invoke
from incident.tools.registry import TOOLS, app_tools
from incident.tools.store import Store

SCEN = Path(__file__).resolve().parents[2] / "scenarios"


def _data(name: str) -> Dataset:
    return Dataset.model_validate_json((SCEN / name / "data.json").read_text("utf-8"))


APP = _data("a02_prompt_guesses")
OLD = _data("s01_bad_deploy")


async def _call(data: Dataset, tool: str, args: dict[str, object]) -> dict[str, object]:
    out = await invoke(Store(data), tool, args, retries=0, backoff_s=0)  # type: ignore[arg-type]
    assert out.ok and out.result_json, out.error
    result: dict[str, object] = json.loads(out.result_json)
    return result


def test_app_tools_are_offered_only_for_datasets_that_have_the_records() -> None:  # covers: R4
    assert app_tools(OLD) == []
    assert app_tools(APP) == ["message_funnel", "conversation_trace", "get_code_change"]
    assert app_tools(APP, "observability") == ["message_funnel", "conversation_trace"]
    assert app_tools(APP, "dependency") == ["get_code_change"]
    assert not set(app_tools(APP)) & set(TOOLS)  # the default tool set is unchanged


async def test_funnel_windows_add_up_to_every_message() -> None:  # covers: R4
    res = await _call(APP, "message_funnel", {"step_min": 30})
    items = res["items"]
    assert isinstance(items, list)
    assert sum(w["received"] for w in items) == len(APP.conversations)
    assert sum(w["answered_after_tool_failure"] for w in items) > 0


async def test_trace_filters_and_reports_an_honest_total() -> None:  # covers: R4, R5
    res = await _call(APP, "conversation_trace", {"tool_failed": True, "limit": 3})
    items = res["items"]
    assert isinstance(items, list) and len(items) == 3 and res["truncated"] is True
    total = res["total"]
    assert isinstance(total, int) and total > 3
    assert all(any(not t["ok"] for t in c["tool_calls"]) for c in items)


async def test_code_change_links_a_deploy_to_its_diff() -> None:  # covers: R4
    deploys = [c for c in APP.changes if c.kind == "deploy" and c.service == "worker"]
    res = await _call(APP, "get_code_change", {"ref": deploys[-1].ref})
    items = res["items"]
    assert isinstance(items, list) and items[0]["files"][0]["patch"]


@pytest.mark.parametrize("tool", ["message_funnel", "conversation_trace", "get_code_change"])
async def test_app_tools_refuse_datasets_without_records(tool: str) -> None:  # covers: R5
    out = await invoke(Store(OLD), tool, {}, retries=0, backoff_s=0)  # type: ignore[arg-type]
    assert not out.ok and out.error is not None and out.error.kind == "invalid_input"
