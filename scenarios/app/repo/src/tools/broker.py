"""Broker tool: order status from the partner broker's REST API."""

import httpx

BASE = "https://api.partner-broker.example/v2"


def order_status(user, timeout):
    resp = httpx.get(f"{BASE}/orders", params={"client": user, "limit": 5}, timeout=timeout)
    resp.raise_for_status()
    return {"orders": resp.json()["orders"]}
