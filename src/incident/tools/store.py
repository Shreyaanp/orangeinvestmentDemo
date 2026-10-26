"""Per-investigation tool state: the dataset, call ids, attempt counters, raw results."""

from collections import Counter
from pathlib import Path
from typing import Self

from incident.models import Dataset, ToolFault, ToolName


class Store:
    """One Store per investigation. Counters are not shared across runs."""

    def __init__(self, data: Dataset) -> None:
        self.data = data
        self.results: dict[str, str] = {}  # call_id -> raw result json, for grounding checks
        self.calls = 0
        self.per_prefix: Counter[str] = Counter()
        self.attempts: Counter[str] = Counter()

    @classmethod
    def load(cls, scenario_dir: Path) -> Self:
        return cls(Dataset.model_validate_json((scenario_dir / "data.json").read_text("utf-8")))

    def new_call_id(self, prefix: str = "tc") -> str:
        """Ids are numbered per prefix, so parallel agents get stable ids (replayable runs)."""
        self.calls += 1
        self.per_prefix[prefix] += 1
        return f"{prefix}-{self.per_prefix[prefix]:02d}"

    def begin_attempt(self, tool: ToolName) -> ToolFault | None:
        """Count one attempt on `tool` (retries count) and return the fault injected on it."""
        self.attempts[tool] += 1
        n = self.attempts[tool]
        faults = self.data.tool_faults
        return next(
            (f for f in faults if f.tool == tool and (not f.on_calls or n in f.on_calls)), None
        )
