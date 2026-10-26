"""LLM gateway client: a planning call (which tools) and an answer call (prompt + tool results)."""

import json
import os
from types import SimpleNamespace

import httpx

GATEWAY = os.environ["LLM_GATEWAY_URL"]
CONFIG = json.load(open("config/app.json"))


def _complete(system, user):
    body = {"model": CONFIG["llm"]["model"], "system": system, "input": user}
    return httpx.post(f"{GATEWAY}/v1/complete", json=body, timeout=20).json()["text"]


def plan(text, ctx, tools):
    system = f"Pick the tools needed to answer, from {tools}. Reply as JSON: {{\"tools\": [...]}}"
    if "portfolio" in ctx:
        system += " A fresh portfolio snapshot is in CONTEXT; do not fetch it again."
    return SimpleNamespace(**json.loads(_complete(system, json.dumps({"text": text, "ctx": ctx}))))


def answer(text, ctx, results, prompt):
    system = open(f"prompts/answer.txt").read()
    payload = {"text": text, "context": ctx, "tool_results": results, "prompt_version": prompt}
    return _complete(system, json.dumps(payload))
