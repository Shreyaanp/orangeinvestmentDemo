"""CloudWatch-style metrics and logs, counted from the simulated events (never written directly)."""

import random
from collections import defaultdict
from datetime import datetime, timedelta

from incident.models import Level, LogLine, Series
from incident.sim.app.engine import Msg, Sim
from incident.sim.app.worker import Span

INFO_SAMPLE = 0.35  # INFO lines are sampled, like a production log pipeline; WARN/ERROR are kept


def _service_metrics(spans: list[Span], minutes: int) -> Series:
    acc: dict[str, list[list[float]]] = defaultdict(
        lambda: [[0.0, 0.0, 0.0] for _ in range(minutes)]
    )
    for sp in spans:
        if sp.t < minutes:
            cell = acc[sp.service][int(sp.t)]
            cell[0] += 1
            cell[1] += not sp.ok
            cell[2] += sp.ms
    out: Series = {}
    for svc, cells in acc.items():
        out[svc] = {
            "rps": [round(c[0] / 60, 3) for c in cells],
            "err_rate": [round(c[1] / c[0], 3) if c[0] else 0.0 for c in cells],
            "latency_ms": [round(c[2] / c[0], 1) if c[0] else None for c in cells],
        }
    return out


def _queue(waits: list[tuple[float, float, float]], minutes: int) -> dict[str, list[float | None]]:
    depth, age = [0.0] * minutes, [0.0] * minutes
    for visible, taken, first in waits:
        for m in range(max(0, int(visible) + 1), min(minutes, int(min(taken, minutes)) + 1)):
            if visible <= m < taken:
                depth[m] += 1
                age[m] = max(age[m], round((m - first) * 60))
    return {"depth": list(depth), "oldest_age_s": list(age)}


def _worker_extra(sim: Sim, minutes: int) -> dict[str, list[float | None]]:
    busy, throttles, dlq = [0.0] * minutes, [0.0] * minutes, [0.0] * minutes
    for sp in sim.spans:
        if sp.service == "worker":
            t, left = sp.t, sp.ms / 60000
            while left > 0 and t < minutes:
                step = min(left, int(t) + 1 - t)
                busy[int(t)] += step
                t, left = t + step, left - step
    for t in sim.throttles:
        throttles[min(int(t), minutes - 1)] += 1
    for t in sim.dlq:
        for m in range(int(t), minutes):
            dlq[m] += 1
    return {
        "concurrency": [round(b, 2) for b in busy],
        "throttles": list(throttles),
        "dlq_depth": list(dlq),
    }


def _per_min(times: list[float], minutes: int) -> list[float | None]:
    out: list[float | None] = [0.0] * minutes
    for t in times:
        if t < minutes:
            out[int(t)] = (out[int(t)] or 0) + 1
    return out


def metrics(sim: Sim, minutes: int) -> Series:
    out = _service_metrics(sim.spans, minutes)
    extra = _worker_extra(sim, minutes)
    out["worker"].update({"concurrency": extra["concurrency"], "throttles": extra["throttles"]})
    for q, waits in sim.waits.items():
        out[q] = _queue(waits, minutes)
    out["sqs-inbound"]["dlq_depth"] = extra["dlq_depth"]
    out["sqs-inbound"]["sent"] = _per_min([m.received for m in sim.msgs], minutes)
    out["sqs-outbound"]["sent"] = _per_min([m.reply_at for m in sim.msgs if m.reply_at], minutes)
    down = [0.0] * minutes
    for m in sim.msgs:
        if m.feedback == "down" and m.reply_at is not None and m.reply_at < minutes:
            down[int(m.reply_at)] += 1
    out["wa-webhook"]["thumbs_down"] = list[float | None](down)
    return out


def _line(sp: Span, msgs: dict[str, Msg]) -> tuple[str, Level, str] | None:
    """(service, level, text) for a span, or None when nothing is logged for it."""
    m = msgs.get(sp.msg)
    intent = m.job.intent if m else "?"
    if sp.service == "wa-webhook":
        return "wa-webhook", "INFO", f"received {sp.detail} message {sp.msg}"
    if sp.service == "worker":
        if sp.ok:
            return "worker", "INFO", f"processed {sp.msg} intent={intent} duration_ms={sp.ms:.0f}"
        return "worker", "ERROR", f"{sp.msg} failed: {sp.detail}"
    if sp.service in ("rds-postgres", "broker-api", "aa-api") and not sp.ok:
        tool = {"rds-postgres": "portfolio", "broker-api": "broker", "aa-api": "aa"}[sp.service]
        return "worker", "WARN", f"tool {tool} failed for {sp.msg}: {sp.detail}"
    if sp.service == "llm-gateway":
        if sp.ok:
            return "llm-gateway", "INFO", f"completion {sp.detail} latency_ms={sp.ms:.0f}"
        return "llm-gateway", "ERROR", f"upstream overloaded (529) {sp.detail}"
    if sp.service == "sender":
        if sp.ok:
            return "sender", "INFO", f"sent reply for {sp.msg}"
        return "sender", "WARN", f"{sp.detail} ({sp.msg})"
    return None


def logs(sim: Sim, start: datetime, rng: random.Random) -> list[LogLine]:
    msgs = {m.job.id: m for m in sim.msgs}
    out = []
    for sp in sim.spans:
        got = _line(sp, msgs)
        if got is None or (got[1] == "INFO" and rng.random() > INFO_SAMPLE):
            continue
        svc, level, text = got
        ts = start + timedelta(minutes=sp.t + sp.ms / 60000)
        host = f"{svc}-{rng.randrange(1, 4)}"
        out.append(
            LogLine(ts=ts.replace(microsecond=0), service=svc, host=host, level=level, msg=text)
        )
    for m in sim.msgs:
        if m.delivery and m.delivery.startswith("failed"):
            ts = start + timedelta(minutes=m.stages[-1][1])
            out.append(
                LogLine(
                    ts=ts.replace(microsecond=0),
                    service="sender",
                    host="sender-1",
                    level="ERROR",
                    msg=f"giving up on reply for {m.job.id}: {m.delivery}",
                )
            )
    return sorted(out, key=lambda ln: ln.ts)
