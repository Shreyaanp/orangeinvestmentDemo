"""Per-run trace: every agent step, tool call and decision as one JSON line."""

import json
import time
from pathlib import Path
from typing import Any


class Trace:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self.events: list[dict[str, Any]] = []
        self.t0 = time.monotonic()
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, kind: str, **fields: Any) -> None:
        ev = {"seq": len(self.events) + 1, "t": round(time.monotonic() - self.t0, 2), "kind": kind}
        ev.update(fields)
        self.events.append(ev)
        if self.path:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(ev, default=str) + "\n")
