"""Conversation session in ElastiCache Redis: recent turns and the last portfolio snapshot."""

import json
import time

import redis

r = redis.Redis(host="session-cache", port=6379)


def load(user, ttl_s):
    raw = r.get(f"session:{user}")
    ctx = json.loads(raw) if raw else {"turns": []}
    snap = ctx.get("portfolio")
    if snap and time.time() - snap["at"] > ttl_s:
        ctx.pop("portfolio")  # too old to quote to the user; the worker fetches fresh data
    return ctx


def save(user, ctx, results):
    if "portfolio" in results and "error" not in results["portfolio"]:
        ctx["portfolio"] = {**results["portfolio"], "at": time.time()}
    r.set(f"session:{user}", json.dumps(ctx), ex=86400)
