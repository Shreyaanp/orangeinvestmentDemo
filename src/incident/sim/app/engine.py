"""Event-level run of the app: messages arrive, wait in SQS for a worker slot, are retried or
dead-lettered, and replies are sent through a rate-limited WhatsApp API."""

import heapq
import random
from collections import Counter
from dataclasses import dataclass, field

from incident.sim.app.spec import AppRecipe, AppWorld
from incident.sim.app.worker import Job, Outcome, Span, State, User, attempt, lognorm

INF = float("inf")
SEND_TRIES = 5


@dataclass
class Msg:
    job: Job
    received: float
    text: str
    attempts: int = 0
    status: str = "in_flight"
    out: Outcome | None = None
    reply_at: float | None = None
    delivery: str | None = None
    feedback: str | None = None
    stages: list[tuple[str, float, float, bool, str]] = field(default_factory=list)


@dataclass
class Sim:
    msgs: list[Msg]
    spans: list[Span] = field(default_factory=list)
    waits: dict[str, list[tuple[float, float, float]]] = field(
        default_factory=lambda: {"sqs-inbound": [], "sqs-outbound": []}
    )  # queue -> (visible from, taken at, first received)
    dlq: list[float] = field(default_factory=list)
    throttles: list[float] = field(default_factory=list)


def make_users(world: AppWorld, rng: random.Random) -> list[User]:
    users = []
    for _ in range(world.users):
        value = round(lognorm(rng, 250_000, 0.8), -2)
        then = round(value * (1 + rng.gauss(0, 0.04)), -2)
        orders = rng.choice(["INFY x10 executed", "TCS x2 open", "HDFCBANK x5 executed"])
        users.append(
            User(f"91{rng.randrange(10**9):09d}", value, (-rng.uniform(120, 1200), then), orders)
        )
    return users


def arrivals(
    world: AppWorld, recipe: AppRecipe, states: list[State], rng: random.Random
) -> list[Msg]:
    users, msgs, t = make_users(world, rng), list[Msg](), 0.0
    kinds, intents = list(world.kinds), world.intents
    while True:
        t += rng.expovariate(recipe.rate_per_min * float(states[int(t)]["traffic_mult"]))
        if t >= recipe.minutes:
            return msgs
        intent = rng.choices(intents, weights=[i.share for i in intents])[0]
        kind = rng.choices(kinds, weights=list(world.kinds.values()))[0]
        text = rng.choice(intent.texts) if kind == "text" else f"[{kind}] {intent.texts[0]}"
        job = Job(f"wamid.{len(msgs) + 1:05d}", rng.choice(users), kind, intent.name, intent.tools)
        msgs.append(Msg(job, t, text))


def _wrong(m: Msg, out: Outcome) -> bool:
    a = out.answer or ""
    if m.job.intent in ("balance", "holdings"):
        return "Sorry" not in a and f"{m.job.user.value:,.0f}" not in a
    return m.job.intent == "order_status" and "executed successfully" in a


def _finish(m: Msg, out: Outcome, end: float) -> None:
    m.out, m.reply_at, m.status = out, end, "replied"
    if any(c.tool == "portfolio" and c.ok for c in out.calls):
        m.job.user.snapshot = (end, m.job.user.value)  # session.save stores the fresh snapshot


def _run_attempt(sim: Sim, m: Msg, s: State, start: float, rng: random.Random) -> Outcome:
    m.attempts += 1
    out = attempt(rng, s, start, m.job)
    sim.spans.append(Span(start, "worker", "invoke", out.ok, out.ms, m.job.id, out.error))
    sim.spans += out.spans
    m.stages.append(("worker", start, out.ms, out.ok, out.error or f"attempt {m.attempts}"))
    return out


def process_inbound(sim: Sim, states: list[State], rng: random.Random, horizon: float) -> None:
    heap = [(m.received + lognorm(rng, 0.0008), i) for i, m in enumerate(sim.msgs)]
    heapq.heapify(heap)
    free: list[float] = []
    while heap:
        avail, i = heapq.heappop(heap)
        m, s = sim.msgs[i], states[min(int(avail), len(states) - 1)]
        slots = max(1, int(float(s["worker.reserved_concurrency"])))
        free += [0.0] * (slots - len(free))
        slot = min(range(slots), key=free.__getitem__)
        start = max(avail, free[slot])
        sim.waits["sqs-inbound"].append((avail, start if start < horizon else INF, m.received))
        if start > avail:
            sim.throttles.append(avail)
        if start >= horizon:
            continue
        m.stages.append(
            ("queue", avail, (start - avail) * 60000, True, f"receive {m.attempts + 1}")
        )
        out = _run_attempt(sim, m, states[int(start)], start, rng)
        free[slot] = start + out.ms / 60000
        visible_again = start + float(s["sqs.visibility_timeout_s"]) / 60
        if out.ok:
            _finish(m, out, free[slot])
        elif m.attempts >= int(float(s["sqs.max_receive_count"])):
            m.status = "dlq"
            sim.dlq.append(visible_again)
        else:
            heapq.heappush(heap, (visible_again, i))


def _deliver(sim: Sim, m: Msg, t: float, rng: random.Random) -> None:
    m.delivery = "delivered"
    m.stages.append(("delivery", t + rng.uniform(1, 4) / 60, 0, True, "delivered"))
    assert m.out is not None
    p_down = 0.4 if _wrong(m, m.out) else 0.15 if "Sorry" in (m.out.answer or "") else 0.03
    m.feedback = "down" if rng.random() < p_down else "up" if rng.random() < 0.2 else None


def send_replies(sim: Sim, states: list[State], rng: random.Random, horizon: float) -> None:
    heap = [(m.reply_at + 0.0005, i, 0) for i, m in enumerate(sim.msgs) if m.reply_at is not None]
    heapq.heapify(heap)
    sent: Counter[int] = Counter()
    while heap:
        t, i, k = heapq.heappop(heap)
        m = sim.msgs[i]
        assert m.reply_at is not None
        if k == 0:
            sim.waits["sqs-outbound"].append((m.reply_at, t if t < horizon else INF, m.reply_at))
        if t >= horizon:
            m.status = "in_flight"
            continue
        ms, limit = lognorm(rng, 180), float(states[int(t)]["whatsapp.rate_limit_per_min"])
        if sent[int(t)] < limit:
            sent[int(t)] += 1
            sim.spans.append(Span(t, "sender", "send", True, ms, m.job.id))
            m.stages.append(("sender", t, ms, True, f"try {k + 1}"))
            _deliver(sim, m, t, rng)
            continue
        error = "WhatsApp API 429 code=130429: throughput limit reached"
        sim.spans.append(Span(t, "sender", "send", False, ms, m.job.id, f"{error}; try {k + 1}"))
        m.stages.append(("sender", t, ms, False, error))
        if k + 1 >= SEND_TRIES:
            m.status, m.delivery = "failed", "failed: 130429 throughput limit"
        else:
            heapq.heappush(heap, (t + 0.5 * 2**k, i, k + 1))


def run(world: AppWorld, recipe: AppRecipe, states: list[State], rng: random.Random) -> Sim:
    sim = Sim(arrivals(world, recipe, states, rng))
    for m in sim.msgs:
        detail = f"{m.job.kind} from {m.job.user.id}"
        sim.spans.append(
            Span(m.received, "wa-webhook", "receive", True, lognorm(rng, 45), m.job.id, detail)
        )
        m.stages.append(("webhook", m.received, 45, True, "enqueued to sqs-inbound"))
    process_inbound(sim, states, rng, recipe.minutes)
    send_replies(sim, states, rng, recipe.minutes)
    return sim
