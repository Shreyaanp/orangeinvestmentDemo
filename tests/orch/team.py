"""A scripted agent team for offline tests. It really calls the tools and quotes their output,
so grounding, scoring and orchestration run for real; only the LLM judgement is scripted."""

import json
import re
from collections import Counter
from typing import Any


def calls(*c: dict[str, Any]) -> str:
    return json.dumps({"tool_calls": list(c)})


def final(obj: dict[str, Any]) -> str:
    return json.dumps({"final": obj})


def tool_result(prompt: str, name: str) -> dict[str, Any]:
    m = re.findall(rf'<tool_result name="{name}">(.*?)</tool_result>', prompt, re.S)
    return json.loads(m[-1]) if m else {}


def ledger(prompt: str) -> list[tuple[str, str, str]]:
    return re.findall(r"^(E-\d+) \[(FACT|ASSUMPTION)[^\]]*\] ([\w-]+)", prompt, re.M)


class Team:
    """Callable fake for LlmFactory(script=...). Knobs let a test break specific agents."""

    def __init__(self, *, metrics_for: str | None = None, challenge_first: bool = False) -> None:
        self.metrics_for, self.challenge_first = metrics_for, challenge_first
        self.crash: set[str] = set()
        self.garbage: set[str] = set()
        self.log: list[str] = []

    def __call__(self, key: str, n: int, system: str, prompt: str) -> str:
        self.log.append(f"{key}#{n}")
        role = key.split("/")[0]
        if role in self.crash:
            raise RuntimeError(f"{role} crashed")
        if role in self.garbage:
            return "this is not json"
        return getattr(self, role)(key, n, prompt)

    def planner(self, key: str, n: int, prompt: str) -> str:
        return final({"tasks": [
            {"agent": "observability", "goal": "Find the first errors around the incident"},
            {"agent": "dependency", "goal": "List recent changes of every kind"},
        ]})  # fmt: skip

    def observability(self, key: str, n: int, prompt: str) -> str:
        if self.metrics_for:
            return self._metrics(n, prompt)
        if n == 1:
            return calls({"name": "query_logs", "args": {"level": "ERROR", "limit": 10}})
        res = tool_result(prompt, "query_logs")
        ev = [
            {"kind": "FACT", "claim": f"error: {s}", "excerpt": s, "source_call_id": res["call_id"],
             "service": s.split()[2].rstrip(":")}
            for s in res["items"][:3]
        ]  # fmt: skip
        return final({"summary": "errors found", "evidence": ev, "gaps": []})

    def _metrics(self, n: int, prompt: str) -> str:
        if n == 1:
            return calls({"name": "query_metrics", "args": {"service": self.metrics_for}})
        res = tool_result(prompt, "query_metrics")
        if not res.get("ok"):
            return final(
                {"summary": "metrics unavailable", "evidence": [], "gaps": ["metrics failed"]}
            )
        item = res["items"][0]
        text = f"{item['metric']} max {item['stats']['max']} min {item['stats']['min']}"
        ev = [{"kind": "FACT", "claim": text, "excerpt": text, "source_call_id": res["call_id"],
               "service": item["service"]}]  # fmt: skip
        return final({"summary": "metrics read", "evidence": ev, "gaps": []})

    def dependency(self, key: str, n: int, prompt: str) -> str:
        if n == 1:
            kinds = ["deploy", "config", "migration", "flag"]
            return calls({"name": "get_changes", "args": {"kinds": kinds}})
        res = tool_result(prompt, "get_changes")
        c = res["items"][-1]
        text = f"{c['ref']} {c['note']}"
        ev = [{"kind": "FACT", "claim": f"change {text}", "excerpt": text,
               "source_call_id": res["call_id"], "service": c["service"], "ts": c["ts"]}]  # fmt: skip
        return final({"summary": "changes listed", "evidence": ev, "gaps": []})

    def reasoning(self, key: str, n: int, prompt: str) -> str:
        rows = [r for r in ledger(prompt) if r[1] == "FACT"]
        if not rows:
            return final({"hypotheses": [], "rejected": []})
        component = Counter(r[2] for r in rows).most_common(1)[0][0]
        ids = [r[0] for r in rows if r[2] == component]
        h = {"id": "H1", "statement": f"{component} is failing", "component": component,
             "cause_type": "test_cause", "supporting": ids}  # fmt: skip
        return final({"hypotheses": [h], "rejected": []})

    def critic(self, key: str, n: int, prompt: str) -> str:
        if self.challenge_first and key.endswith("/r1"):
            ch = {"target": "H1", "kind": "missing_coverage", "objection": "metrics not checked",
                  "requested_check": "Check the error rate metric of the suspected service",
                  "agent": "observability"}  # fmt: skip
            return final({"approve": False, "rationale": "needs metrics", "challenges": [ch]})
        return final({"approve": True, "rationale": "solid", "challenges": []})

    def reporting(self, key: str, n: int, prompt: str) -> str:
        ids = [r[0] for r in ledger(prompt)]
        cite = ids[:1] or ["E-001"]
        return final({
            "summary": "Scripted report.",
            "hypotheses": [{"hypothesis_id": "H1", "supporting": [{"text": "evidence", "evidence_ids": cite}]}],
            "actions": [{"text": "roll back", "rationale": "why", "evidence_ids": cite, "priority": "immediate"}],
            "unresolved": [],
        })  # fmt: skip

    def baseline(self, key: str, n: int, prompt: str) -> str:
        if n == 1:
            return calls({"name": "query_logs", "args": {"level": "ERROR", "limit": 10}})
        res = tool_result(prompt, "query_logs")
        ev = [{"ref": f"e{i}", "kind": "FACT", "claim": s, "excerpt": s, "source_call_id": res["call_id"],
               "service": s.split()[2].rstrip(":")} for i, s in enumerate(res["items"][:3], 1)]  # fmt: skip
        h = {"id": "H1", "statement": "x is failing", "component": ev[0]["service"], "cause_type": "t",
             "supporting": ["e1", "e2", "e3"]}  # fmt: skip
        act = {
            "text": "roll back",
            "rationale": "r",
            "evidence_ids": ["e1"],
            "priority": "immediate",
        }
        return final({"summary": "baseline", "evidence": ev, "hypotheses": [h], "actions": [act]})
