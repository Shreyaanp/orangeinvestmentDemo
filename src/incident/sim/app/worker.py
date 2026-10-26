"""One worker attempt on one message: session, LLM plan, tools, LLM answer. Every step is a span;
the answer is what the model would say given the prompt behaviour and the tool results."""

import math
import random
from dataclasses import dataclass, field

from incident.app_models import ToolCallRecord
from incident.sim.app.spec import Value

State = dict[str, Value]
BACKEND = {"portfolio": "rds-postgres", "broker": "broker-api", "aa": "aa-api"}


@dataclass
class Span:
    t: float  # minutes from start
    service: str
    op: str
    ok: bool
    ms: float
    msg: str
    detail: str = ""


@dataclass
class User:
    id: str
    value: float  # portfolio value now
    snapshot: tuple[float, float]  # (minute it was cached, value then); minute < 0 = before start
    orders: str


@dataclass
class Outcome:
    ok: bool
    ms: float
    error: str = ""
    context: list[str] = field(default_factory=list)
    calls: list[ToolCallRecord] = field(default_factory=list)
    answer: str | None = None
    spans: list[Span] = field(default_factory=list)


def lognorm(rng: random.Random, median: float, sigma: float = 0.35) -> float:
    return median * math.exp(rng.gauss(0, sigma))


def _num(s: State, key: str) -> float:
    v = s[key]
    if isinstance(v, bool | str):
        raise TypeError(f"state key {key} is not a number: {v!r}")
    return float(v)


def _tool(rng: random.Random, s: State, name: str, user: User) -> tuple[bool, float, str]:
    lat = lognorm(rng, _num(s, f"tool.{name}.latency_ms"), _num(s, f"tool.{name}.sigma"))
    timeout_s = _num(s, f"tools.{name}.timeout_s")
    error = str(s.get(f"tool.{name}.error", ""))
    if error:
        return False, lat * 0.3, error
    if lat > timeout_s * 1000:
        return False, timeout_s * 1000, f"ReadTimeout: timed out after {timeout_s:g}s"
    if rng.random() < _num(s, f"tool.{name}.error_rate"):
        return False, lat, str(s.get(f"tool.{name}.flaky_error", "HTTPStatusError: 503"))
    ok_text = {
        "portfolio": f"value=INR {user.value:,.0f}; holdings=6",
        "broker": f"orders: {user.orders}",
        "aa": "accounts refreshed: 2",
    }
    return True, lat, ok_text[name]


def _llm(rng: random.Random, s: State, t: float, out: Outcome, mid: str, op: str) -> bool:
    base = 900.0 if op == "plan" else 1600.0
    ms = lognorm(rng, base * _num(s, "llm.latency_mult"), 0.25)
    ok = rng.random() >= _num(s, "llm.error_rate")
    detail = f"model={s['llm.model']} prompt={s['llm.prompt_version']} op={op}"
    out.spans.append(Span(t + out.ms / 60000, "llm-gateway", op, ok, ms, mid, detail))
    out.ms += ms
    if not ok:
        out.error = "LLMGatewayError: 529 overloaded"
    return ok


def answer_text(
    intent: str, results: dict[str, str], failed: list[str], s: State, user: User
) -> str:
    if failed and s["prompt.on_tool_error"] == "guess":  # the model fills the gap itself
        if intent == "order_status":
            return "Your last order was executed successfully."
        return f"Your portfolio is worth INR {round(user.value * 0.83, -3):,.0f} today."
    if failed:
        return "Sorry, I couldn't fetch that right now. Shall I try again in a few minutes?"
    if intent in ("balance", "holdings"):
        value = results.get("portfolio", "")
        return f"Your portfolio is worth {value.split(';')[0].removeprefix('value=')} right now."
    if intent == "order_status":
        return f"Your recent orders: {results['broker'].removeprefix('orders: ')}."
    if intent == "refresh":
        return "Done, I refreshed your 2 linked bank accounts."
    return "Markets are open; NIFTY is trading in a narrow range today."


def _session(rng: random.Random, s: State, t: float, user: User, out: Outcome, mid: str) -> bool:
    ms = lognorm(rng, 2.0)
    out.spans.append(Span(t, "redis-session", "get", True, ms, mid))
    out.ms += ms
    at, value = user.snapshot
    age_s = (t - at) * 60
    fresh = age_s <= _num(s, "session.ttl_s")
    if fresh:
        out.context.append(f"portfolio snapshot from session cache, age {age_s:.0f}s")
    return fresh


@dataclass
class Job:
    id: str
    user: User
    kind: str
    intent: str
    tools: list[str]


def _call_tools(
    rng: random.Random, s: State, t: float, job: Job, out: Outcome, cached: bool
) -> tuple[dict[str, str], list[str]]:
    results, failed = {}, []
    if cached:
        results["portfolio"] = f"value=INR {job.user.snapshot[1]:,.0f}; holdings=6"
    for name in [n for n in job.tools if not (cached and n == "portfolio")]:
        ok, ms, text = _tool(rng, s, name, job.user)
        at = t + out.ms / 60000
        out.spans.append(Span(at, BACKEND[name], "call", ok, ms, job.id, text))
        out.calls.append(ToolCallRecord(tool=name, ok=ok, ms=round(ms), result=text))
        out.ms += ms
        if ok:
            results[name] = text
        else:
            failed.append(name)
    return results, failed


def attempt(rng: random.Random, s: State, t: float, job: Job) -> Outcome:
    out = Outcome(ok=False, ms=0)
    if s.get("worker.crash_on_kind") == job.kind:
        out.ms, out.error = lognorm(rng, 60), str(s["worker.crash_error"])
        return out
    cached = _session(rng, s, t, job.user, out, job.id)
    if not _llm(rng, s, t, out, job.id, "plan"):
        return out
    results, failed = _call_tools(rng, s, t, job, out, cached)
    if not _llm(rng, s, t, out, job.id, "answer"):
        return out
    limit_s = _num(s, "worker.timeout_s")
    if out.ms > limit_s * 1000:
        out.ms, out.error = limit_s * 1000, f"Task timed out after {limit_s:.2f} seconds"
        return out
    out.ok, out.answer = True, answer_text(job.intent, results, failed, s, job.user)
    return out
