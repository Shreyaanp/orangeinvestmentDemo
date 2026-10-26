"""Write the static system catalogue the agents get as prior knowledge (incident.knowledge).

Usage: python scripts/build_catalog.py WORLD.json [--repo DIR] --name NAME --out OUT.json
Built from the BASE world (the system as it normally runs) and, when given, the app repository at
its baseline commit: module docstrings, CREATE TABLE statements, config keys. Never from an
incident's data, so it cannot carry the answer. Run it again whenever the world or repo changes.
"""

import argparse
import json
import re
from pathlib import Path
from typing import Any

from incident.knowledge import Catalogue, Module, ServiceInfo, Table
from incident.models import QueueDef

BASE_METRICS = ["rps", "latency_ms", "err_rate"]


def _services(world: dict[str, Any]) -> list[ServiceInfo]:
    raw = world["services"]
    specs = raw if isinstance(raw, dict) else {name: {} for name in raw}
    calls: dict[str, list[str]] = {}
    for e in world.get("edges", []):
        calls.setdefault(e["caller"], []).append(e["callee"])
    out = []
    for name, spec in specs.items():
        activity = [re.sub(r"\s*\{\w+\}", "", t).strip() for t in spec.get("info_logs", [])]
        out.append(
            ServiceInfo(
                name=name,
                purpose=f"normal activity: {'; '.join(activity)}" if activity else "",
                calls=calls.get(name, []),
                metrics=[*BASE_METRICS, *spec.get("gauges", {})] if spec else [],
            )
        )
    return out


def _modules(repo: Path) -> list[Module]:
    out = []
    for f in sorted((repo / "src").rglob("*.py")):
        doc = re.match(r'\s*"""(.*?)(?:\n|""")', f.read_text("utf-8"))
        rel = f.relative_to(repo).as_posix()
        out.append(Module(path=rel, doc=doc.group(1).strip() if doc else ""))
    return out


def _tables(repo: Path) -> list[Table]:
    out = []
    for f in sorted((repo / "db").rglob("*.sql")):
        for name, body in re.findall(r"CREATE TABLE (\w+) \((.*?)\);", f.read_text("utf-8"), re.S):
            cols = [c.split()[0] for c in body.splitlines() if c.strip() and c.split()[0].islower()]
            out.append(Table(name=name, columns=cols))
    return out


def _flatten(obj: Any, prefix: str = "") -> dict[str, str]:
    if not isinstance(obj, dict):
        return {prefix: json.dumps(obj)}
    out: dict[str, str] = {}
    for k, v in obj.items():
        out |= _flatten(v, f"{prefix}.{k}" if prefix else k)
    return out


def build(world_path: Path, repo: Path | None, name: str) -> Catalogue:
    world = json.loads(world_path.read_text("utf-8"))
    services = _services(world)
    queues = [
        QueueDef(name=q["name"], publisher=q["publisher"], consumer=q["consumer"])
        for q in world.get("queues", [])
    ]
    cat = Catalogue(system=name, services=services, queues=queues)
    if repo:
        cat.modules = _modules(repo)
        cat.tables = _tables(repo)
        configs = sorted((repo / "config").glob("*.json"))
        cat.config = {k: v for f in configs for k, v in _flatten(json.loads(f.read_text())).items()}
    return cat


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("world", type=Path)
    ap.add_argument("--repo", type=Path)
    ap.add_argument("--name", required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(build(a.world, a.repo, a.name).model_dump_json(indent=1), "utf-8")
    print(f"wrote {a.out}")
