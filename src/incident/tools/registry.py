"""Tool registry: name, description, input model and implementation for each tool."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from incident.models import Dataset, ToolName
from incident.tools import (
    changes,
    code,
    conversations,
    dependencies,
    digest,
    funnel,
    history,
    logs,
    metrics,
)
from incident.tools.schemas import Result


@dataclass(frozen=True)
class ToolSpec:
    name: ToolName
    description: str
    input: type[BaseModel]
    run: Callable[[Dataset, Any], Result[Any]]


TOOLS: dict[ToolName, ToolSpec] = {
    "query_logs": ToolSpec("query_logs", logs.DESCRIPTION, logs.Query, logs.run),
    "query_metrics": ToolSpec("query_metrics", metrics.DESCRIPTION, metrics.Query, metrics.run),
    "get_changes": ToolSpec("get_changes", changes.DESCRIPTION, changes.Query, changes.run),
    "get_dependencies": ToolSpec(
        "get_dependencies", dependencies.DESCRIPTION, dependencies.Query, dependencies.run
    ),
    "search_incidents": ToolSpec(
        "search_incidents", history.DESCRIPTION, history.Query, history.run
    ),
}

# Opt-in digest tools (the "lean" profile). Kept out of TOOLS so the evaluated default is unchanged.
DIGEST: dict[ToolName, ToolSpec] = {
    "get_anomalies": ToolSpec(
        "get_anomalies", digest.ANOMALIES_DESCRIPTION, digest.AnomalyQuery, digest.anomalies
    ),
    "get_log_patterns": ToolSpec(
        "get_log_patterns", digest.PATTERNS_DESCRIPTION, digest.PatternQuery, digest.patterns
    ),
}
DIGEST_NAMES: list[ToolName] = list(DIGEST)

# Application-record tools: offered only when the dataset carries message records / code history.
APP: dict[ToolName, ToolSpec] = {
    "message_funnel": ToolSpec("message_funnel", funnel.DESCRIPTION, funnel.Query, funnel.run),
    "conversation_trace": ToolSpec(
        "conversation_trace", conversations.DESCRIPTION, conversations.Query, conversations.run
    ),
    "get_code_change": ToolSpec("get_code_change", code.DESCRIPTION, code.Query, code.run),
}
APP_ROLE: dict[ToolName, str] = {
    "message_funnel": "observability",
    "conversation_trace": "observability",
    "get_code_change": "dependency",
}
ALL_TOOLS: dict[ToolName, ToolSpec] = {**TOOLS, **DIGEST, **APP}


def app_tools(data: Dataset, role: str | None = None) -> list[ToolName]:
    """The application-record tools this dataset supports, for one specialist role or all."""
    have = {
        "message_funnel": bool(data.conversations),
        "conversation_trace": bool(data.conversations),
        "get_code_change": bool(data.code_changes),
    }
    return [n for n in APP if have[n] and role in (None, APP_ROLE[n])]
