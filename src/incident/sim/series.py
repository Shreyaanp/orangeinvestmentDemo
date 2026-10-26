"""Per-minute metric series: baseline + noise, fault effects, dependency propagation, queues."""

import random

from incident.models import Series
from incident.sim.recipe import Artifact, Effect, Fault, Recipe
from incident.sim.world import World

Num = dict[str, dict[str, list[float]]]
DEADBAND = 1.1


def _init(world: World, m: int, rng: random.Random) -> Num:
    s: Num = {}
    for name, b in world.services.items():
        s[name] = {
            "rps": [b.rps * rng.gauss(1, 0.03) for _ in range(m)],
            "latency_ms": [b.latency_ms * rng.gauss(1, 0.03) for _ in range(m)],
            "err_rate": [max(0.0, b.err_rate * rng.gauss(1, 0.15)) for _ in range(m)],
        }
        for gauge, v in b.gauges.items():
            s[name][gauge] = [v * rng.gauss(1, 0.02) for _ in range(m)]
    for q in world.queues:
        s[q.name] = {
            "publish_rate": [0.0] * m,
            "consume_rate": [0.0] * m,
            "consumers": [float(q.consumers)] * m,
            "depth": [0.0] * m,
            "redeliveries": [0.0] * m,
            "dlq": [0.0] * m,
        }
    return s


def _op(op: str, x: float, v: float, r: float) -> float:
    if op == "add":
        return x + v * r
    if op == "mul":
        return x * (1 + (v - 1) * r)
    return x + (v - x) * r


def _apply(s: Num, f: Fault, e: Effect, m: int) -> None:
    if e.target not in s:
        raise ValueError(f"fault {f.id}: unknown effect target {e.target}")
    arr = s[e.target].setdefault(e.metric, [0.0] * m)
    end = m if f.until_min is None else min(f.until_min, m)
    start = f.at_min + e.after_min
    for t in range(max(start, 0), end):
        r = min(1.0, (t - start + 1) / e.ramp_min) if e.ramp_min else 1.0
        arr[t] = _op(e.op, arr[t], e.value, r)


def _callee_first(world: World) -> list[str]:
    deps = {n: [e.callee for e in world.edges if e.caller == n] for n in world.services}
    order: list[str] = []
    seen: set[str] = set()

    def visit(n: str) -> None:
        if n in seen:
            return
        seen.add(n)
        for c in deps[n]:
            visit(c)
        order.append(n)

    for n in world.services:
        visit(n)
    return order


def _propagate(s: Num, world: World) -> None:
    for caller in _callee_first(world):
        for e in (x for x in world.edges if x.caller == caller):
            base = world.services[e.callee]
            lat, err = s[e.callee]["latency_ms"], s[e.callee]["err_rate"]
            mine_lat, mine_err = s[caller]["latency_ms"], s[caller]["err_rate"]
            for t in range(e.lag_min, len(lat)):
                u = t - e.lag_min
                mine_lat[t] += e.weight * max(0.0, lat[u] - DEADBAND * base.latency_ms)
                excess = max(0.0, err[u] - 2 * base.err_rate - 0.002)
                mine_err[t] = min(1.0, mine_err[t] + e.weight * excess)


def _derive_queues(s: Num, world: World) -> None:
    for q in world.queues:
        qs, pub, con = s[q.name], world.services[q.publisher], world.services[q.consumer]
        for t in range(len(qs["depth"])):
            qs["publish_rate"][t] = q.base_publish * s[q.publisher]["rps"][t] / pub.rps
            slow = min(1.0, con.latency_ms / s[q.consumer]["latency_ms"][t])
            err = min(1.0, s[q.consumer]["err_rate"][t])
            qs["consume_rate"][t] = (
                q.base_consume * qs["consumers"][t] / q.consumers * slow * (1 - err)
            )
            qs["redeliveries"][t] = qs["consume_rate"][t] * err * 2


def _integrate_depth(s: Num, world: World) -> None:
    for q in world.queues:
        qs, depth = s[q.name], 0.0
        for t in range(len(qs["depth"])):
            depth = max(0.0, depth + qs["publish_rate"][t] - qs["consume_rate"][t])
            qs["depth"][t] = depth


def build_series(world: World, recipe: Recipe, rng: random.Random) -> Num:
    s = _init(world, recipe.minutes, rng)
    queues = {q.name for q in world.queues}
    early: list[tuple[Fault, Effect]] = []
    late: list[tuple[Fault, Effect]] = []
    for f in recipe.faults:
        for e in f.effects:
            is_early = e.target not in queues or e.metric == "consumers"
            (early if is_early else late).append((f, e))
    for f, e in early:
        _apply(s, f, e, recipe.minutes)
    _propagate(s, world)
    _derive_queues(s, world)
    for f, e in late:
        _apply(s, f, e, recipe.minutes)
    _integrate_depth(s, world)
    return s


def finalize(s: Num, artifacts: list[Artifact]) -> Series:
    out: Series = {
        n: {k: [round(v, 3) for v in vals] for k, vals in ms.items()} for n, ms in s.items()
    }
    for a in (x for x in artifacts if x.kind == "metric_missing"):
        for key in [a.metric] if a.metric else list(out[a.service]):
            vals = out[a.service][key]
            for t in range(a.from_min, min(a.to_min, len(vals))):
                vals[t] = None
    return out
