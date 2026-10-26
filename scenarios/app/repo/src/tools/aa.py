"""Account Aggregator tool: refresh linked bank accounts through the AA consent."""

import httpx

BASE = "https://aa.example/fiu/v1"


def refresh(user, timeout):
    resp = httpx.post(f"{BASE}/data-fetch", json={"user": user}, timeout=timeout)
    resp.raise_for_status()
    return {"accounts": resp.json()["accounts"]}
