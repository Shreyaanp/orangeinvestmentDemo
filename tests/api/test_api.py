import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "orch"))
from team import Team  # noqa: E402

from incident import api  # noqa: E402
from incident.llm import LlmFactory  # noqa: E402


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):  # type: ignore[no-untyped-def]
    monkeypatch.setattr(api, "LlmFactory", lambda *a, **k: LlmFactory("fake", script=Team()))
    monkeypatch.setattr(api, "RUNS", tmp_path)
    api.runs.clear()
    with TestClient(api.app) as c:
        yield c


def _wait(client: TestClient, run_id: str, headers: dict[str, str] | None = None) -> dict:  # type: ignore[type-arg]
    for _ in range(100):
        body = client.get(f"/investigations/{run_id}", headers=headers).json()
        if body["status"] != "running":
            return body  # type: ignore[no-any-return]
        time.sleep(0.1)
    raise AssertionError("run did not finish")


def test_health_and_scenarios(client: TestClient) -> None:  # covers: R18
    assert client.get("/healthz").json()["ok"] is True
    assert len(client.get("/scenarios").json()) >= 10


def test_full_run_over_http(client: TestClient) -> None:  # covers: R18, R11
    r = client.post("/investigations", json={"scenario_id": "s01_bad_deploy"})
    assert r.status_code == 202
    body = _wait(client, r.json()["run_id"])
    assert body["status"] == "done" and body["report"]["status"] == "ANSWER"
    assert body["report"]["hypotheses"][0]["component"] == "order-router"
    trace = client.get(f"/investigations/{r.json()['run_id']}/trace").json()
    assert {e["kind"] for e in trace} >= {"plan", "task", "tool", "final"}


def test_baseline_system_selectable(client: TestClient) -> None:  # covers: R15
    r = client.post("/investigations", json={"scenario_id": "s01_bad_deploy", "system": "baseline"})
    assert _wait(client, r.json()["run_id"])["report"]["stats"]["rounds"] == 0


def test_every_listed_scenario_can_be_started(client: TestClient) -> None:  # covers: R18
    listed = client.get("/scenarios").json()
    assert {"a01_broker_timeout", "f01_kyc_key_expiry"} <= set(listed)
    r = client.post(
        "/investigations", json={"scenario_id": "a01_broker_timeout", "system": "hybrid"}
    )
    assert r.status_code == 202 and _wait(client, r.json()["run_id"])["status"] == "done"


def test_bad_input_is_rejected(client: TestClient) -> None:  # covers: R5
    for bad in ["../../etc/passwd", "s99_nope", "S01_BAD", "s01_bad_deploy/../x", ""]:
        assert client.post("/investigations", json={"scenario_id": bad}).status_code == 404
    assert (
        client.post(
            "/investigations", json={"scenario_id": "s01_bad_deploy", "system": "x"}
        ).status_code
        == 422
    )
    assert client.get("/investigations/nope").status_code == 404


def test_api_key_is_enforced_when_configured(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("API_KEY", "secret")
    assert client.get("/scenarios").status_code == 401
    assert client.get("/scenarios", headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.get("/scenarios", headers={"X-API-Key": "secret"}).status_code == 200
    assert client.get("/healthz").status_code == 200  # probes stay open


def test_concurrency_is_capped(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:  # covers: R9
    import asyncio

    real = api.investigate

    async def held_open(*a, **k):  # type: ignore[no-untyped-def]
        await asyncio.sleep(0.6)  # the first run is still running when the second arrives
        return await real(*a, **k)

    monkeypatch.setattr(api, "investigate", held_open)
    monkeypatch.setattr(api, "MAX_CONCURRENT", 1)
    first = client.post("/investigations", json={"scenario_id": "s01_bad_deploy"})
    second = client.post("/investigations", json={"scenario_id": "s01_bad_deploy"})
    assert first.status_code == 202 and second.status_code == 429
    _wait(client, first.json()["run_id"])


def test_run_timeout_is_reported_as_an_error(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:  # covers: R9
    monkeypatch.setattr(api, "RUN_TIMEOUT_S", 0.001)
    r = client.post("/investigations", json={"scenario_id": "s01_bad_deploy"})
    body = _wait(client, r.json()["run_id"])
    assert body["status"] == "error" and body["report"] is None
