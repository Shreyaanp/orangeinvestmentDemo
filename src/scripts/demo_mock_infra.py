"""Demo: show that the adapters speak the real wire protocols, against a local mock.

Usage: python scripts/demo_mock_infra.py [scenario_id] [--rate-limit N] [--outage /v2] [--cloud aws]
(Git Bash rewrites a leading "/v2" argument into a Windows path: set MSYS_NO_PATHCONV=1.)
Serves a scenario as Datadog / GitHub / GCP Audit Logs (or CloudFormation) APIs, ingests it
through the real adapters, prints the wire traffic, and checks the result against the original.
"""

import argparse
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from mockworld.apis import Faults  # noqa: E402
from mockworld.ingest import ingest_with_traffic  # noqa: E402

from incident.agents.tools import render  # noqa: E402
from incident.models import Dataset  # noqa: E402
from incident.tools.guard import invoke  # noqa: E402
from incident.tools.store import Store  # noqa: E402


def parity(original: Dataset, snap: Dataset) -> dict[str, bool]:
    def logs(d: Dataset) -> list[tuple]:  # type: ignore[type-arg]
        return sorted((x.ts, x.service, x.host, x.level, x.msg) for x in d.logs)

    def changes(d: Dataset) -> list[tuple]:  # type: ignore[type-arg]
        return sorted((c.ts, c.kind, c.service, c.ref) for c in d.changes)

    same = all(
        snap.metrics.get(s, {}).get(m) == v
        for s, ms in original.metrics.items()
        for m, v in ms.items()
        if any(x is not None for x in v)
    )
    return {
        "logs": logs(original) == logs(snap),
        "metrics": same,
        "changes": changes(original) == changes(snap),
    }


def summarise(calls: list[tuple[str, str, int]]) -> None:
    print("\nWIRE TRAFFIC served by the mock (method, endpoint -> status x count):")
    other = [(m, p, s) for m, p, s in calls if "/repos/" not in p]
    for (m, p, s), n in sorted(Counter(other).items(), key=lambda x: (x[0][1], x[0][2])):
        print(f"  {m:4s} {p:34s} -> {s} x{n}")
    repo = Counter(s for _, p, s in calls if "/repos/" in p)
    print(f"  GitHub repository calls by status: {dict(repo)}")


async def main(a: argparse.Namespace) -> int:
    data = Dataset.model_validate_json(
        (ROOT / "scenarios" / a.scenario / "data.json").read_text("utf-8")
    )
    faults = Faults(rate_limit_every=a.rate_limit, fail_prefix=a.outage)
    snap, warnings, calls = await ingest_with_traffic(data, faults, cloud=a.cloud)
    print(f"\n=== {a.scenario}: {len(data.logs)} log lines, {len(data.changes)} changes")
    summarise(calls)
    print(f"\nwarnings: {warnings or 'none'}")
    result = parity(data, snap)
    cells = "  ".join(f"{k}={'EXACT' if v else 'DIFFERS'}" for k, v in result.items())
    print(f"parity with the original scenario: {cells}")
    shown = render(await invoke(Store(snap), "query_logs", {"level": "ERROR", "limit": 2}))
    keep = {k: shown[k] for k in ("call_id", "total", "items", "sources") if k in shown}
    print("\nWhat the agent sees from query_logs (note the verifiable source link):")
    print(json.dumps(keep, indent=2)[:900])
    return 0 if result["logs"] and result["metrics"] and (result["changes"] or warnings) else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario", nargs="?", default="s03_config_not_deploy")
    ap.add_argument("--rate-limit", type=int, default=0)
    ap.add_argument("--outage", default=None)
    ap.add_argument("--cloud", choices=["gcp", "aws"], default="gcp")
    sys.exit(asyncio.run(main(ap.parse_args())))
