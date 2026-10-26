"""Log emission: routine traffic, symptoms derived from simulated state, fault signature lines."""

import random
from datetime import timedelta

from incident.models import Level, LogLine
from incident.sim.recipe import Artifact, Recipe
from incident.sim.series import DEADBAND, Num
from incident.sim.world import World


class _Safe(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def _num(v: float) -> str:
    return str(round(v) if abs(v) >= 10 else round(v, 3))


class _Emitter:
    def __init__(self, world: World, recipe: Recipe, rng: random.Random) -> None:
        self.world, self.recipe, self.rng = world, recipe, rng
        self.lines: list[LogLine] = []

    def count(self, rate: float) -> int:
        n = int(rate)
        return n + (1 if self.rng.random() < rate - n else 0)

    def add(self, t: int, service: str, level: Level, msg: str) -> None:
        ts = self.recipe.start + timedelta(minutes=t, seconds=self.rng.randrange(60))
        host = f"{service}-{self.rng.randrange(2)}"
        self.lines.append(LogLine(ts=ts, service=service, host=host, level=level, msg=msg))

    def _routine(self, t: int, name: str, level: Level, templates: list[str], rate: float) -> None:
        for _ in range(self.count(rate) if templates else 0):
            vals = _Safe(rid=str(self.rng.randrange(10**6)))
            self.add(t, name, level, self.rng.choice(templates).format_map(vals))

    def routine(self) -> None:
        for name, base in self.world.services.items():
            for t in range(self.recipe.minutes):
                self._routine(t, name, "INFO", base.info_logs, 1.2)
                self._routine(t, name, "WARN", base.noise_logs, 0.15)

    def edge_symptoms(self, s: Num) -> None:
        for e in self.world.edges:
            callee, caller = self.world.services[e.callee], self.world.services[e.caller]
            lat, err = s[e.callee]["latency_ms"], s[e.callee]["err_rate"]
            for t in range(e.lag_min, self.recipe.minutes):
                u = t - e.lag_min
                extra = e.weight * max(0.0, lat[u] - DEADBAND * callee.latency_ms)
                if extra > 0.5 * caller.latency_ms:
                    msg = f"upstream call to {e.callee} timed out after {round(lat[u])}ms"
                    for _ in range(min(4, 1 + int(extra / caller.latency_ms))):
                        self.add(t, e.caller, "WARN", msg)
                if err[u] > 4 * callee.err_rate + 0.01:
                    for _ in range(min(6, 1 + int(err[u] * caller.rps * 0.1))):
                        self.add(t, e.caller, "ERROR", f"{e.callee} call failed: HTTP 503")

    def queue_symptoms(self, s: Num) -> None:
        for q in self.world.queues:
            qs = s[q.name]
            for t in range(self.recipe.minutes):
                if qs["depth"][t] > 3 * q.base_publish:
                    msg = f"queue {q.name}: {round(qs['depth'][t])} messages ready, "
                    self.add(t, "rabbitmq", "WARN", msg + f"{round(qs['consumers'][t])} consumers")
                if qs["redeliveries"][t] > 2:
                    msg = f"redelivered {round(qs['redeliveries'][t])} messages on {q.name}"
                    self.add(t, q.consumer, "WARN", msg)

    def fault_logs(self, s: Num) -> None:
        m = self.recipe.minutes
        for f in self.recipe.faults:
            end = m if f.until_min is None else min(f.until_min, m)
            for rule in f.logs:
                for t in range(max(f.at_min + rule.after_min, 0), end):
                    source = s[rule.series or rule.service]
                    vals = _Safe({k: _num(v[t]) for k, v in source.items()})
                    for _ in range(self.count(rule.per_min)):
                        self.add(t, rule.service, rule.level, rule.msg.format_map(vals))


def _dropped(a: Artifact, ln: LogLine, minute: int, rng: random.Random) -> bool:
    if a.kind != "log_drop" or a.service != ln.service:
        return False
    if not a.from_min <= minute < a.to_min or (a.match and a.match not in ln.msg):
        return False
    return rng.random() >= a.keep_frac


def _artifacts(lines: list[LogLine], recipe: Recipe, rng: random.Random) -> list[LogLine]:
    out: list[LogLine] = []
    for ln in lines:
        minute = int((ln.ts - recipe.start).total_seconds() // 60)
        if any(_dropped(a, ln, minute, rng) for a in recipe.artifacts):
            continue
        skew = sum(
            a.offset_s
            for a in recipe.artifacts
            if a.kind == "clock_skew" and a.service == ln.service
        )
        out.append(ln.model_copy(update={"ts": ln.ts + timedelta(seconds=skew)}) if skew else ln)
    return sorted(out, key=lambda ln: ln.ts)


def build_logs(world: World, recipe: Recipe, s: Num, rng: random.Random) -> list[LogLine]:
    em = _Emitter(world, recipe, rng)
    em.routine()
    em.edge_symptoms(s)
    em.queue_symptoms(s)
    em.fault_logs(s)
    return _artifacts(em.lines, recipe, rng)
