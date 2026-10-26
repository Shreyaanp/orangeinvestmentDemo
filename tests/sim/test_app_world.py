"""The event-level app world: telemetry agrees with the events, faults act through state."""

import json
from pathlib import Path

from incident.models import Dataset
from incident.sim.app import repo
from incident.sim.app.build import load_world, simulate_app
from incident.sim.app.spec import AppChange, AppRecipe, Edit

APP = Path(__file__).resolve().parents[2] / "scenarios" / "app"
WORLD, TREE = load_world(APP)


def _recipe(**extra: object) -> AppRecipe:
    base = {
        "id": "t",
        "seed": 1,
        "start": "2026-10-20T09:00:00Z",
        "minutes": 60,
        "incident_at_min": 50,
        "incident_text": "x",
        "faults": [],
        "trap": "x",
    }
    return AppRecipe.model_validate({**base, **extra})


def _run(**extra: object) -> Dataset:
    return simulate_app(WORLD, TREE, _recipe(**extra))[0]


def test_commit_produces_a_real_diff_and_config_follows_the_tree() -> None:  # covers: R14
    change = AppChange(
        id="c",
        kind="deploy",
        service="worker",
        at_min=0,
        title="t",
        edits=[Edit(path=repo.CONFIG, find='"ttl_s": 300', replace='"ttl_s": 86400')],
    )
    new, diffs = repo.commit(TREE, change)
    assert repo.config_keys(new)["session.ttl_s"] == 86400
    assert diffs[0].path == repo.CONFIG and '+    "ttl_s": 86400' in diffs[0].patch
    assert repo.config_keys(TREE)["session.ttl_s"] == 300  # the base tree is untouched


def test_every_message_is_accounted_for_and_metrics_count_events() -> None:  # covers: R14
    data = _run()
    assert data.conversations and data.code_changes
    statuses = {c.status for c in data.conversations}
    assert statuses <= {"replied", "failed", "dlq", "in_flight"}
    received = sum(v or 0 for v in data.metrics["sqs-inbound"]["sent"])
    assert received == sum(c.received_at < data.start.replace(hour=10) for c in data.conversations)
    llm_calls = sum((v or 0) * 60 for v in data.metrics["llm-gateway"]["rps"])
    assert abs(llm_calls - sum(2 for c in data.conversations if c.answer)) <= 0.05 * llm_calls


def test_console_concurrency_cut_backs_up_the_queue_and_a_later_deploy_keeps_it() -> (
    None
):  # covers: R14
    cut = {"id": "cap", "kind": "config", "service": "worker", "at_min": 10, "title": "cap"}
    data = _run(rate_per_min=24, changes=[{**cut, "set": {"worker.reserved_concurrency": 1}}])
    age = data.metrics["sqs-inbound"]["oldest_age_s"]
    assert max(v or 0 for v in age[:10]) == 0
    assert max(v or 0 for v in age[45:]) > 120  # routine deploys must not reset console changes


def test_failed_ci_is_recorded_but_never_deployed() -> None:  # covers: R14
    edit = {"path": "src/tools/broker.py", "find": 'limit": 5', "replace": 'limit": 10'}
    change = {"id": "x", "kind": "deploy", "service": "worker", "at_min": 20, "title": "t"}
    data = _run(changes=[{**change, "ci": "failure", "edits": [edit]}])
    failed = [c for c in data.code_changes if c.ci == "failure"]
    assert len(failed) == 1 and all(ch.ref != failed[0].ref for ch in data.changes)


def test_guessing_prompt_answers_after_tool_failures_and_apology_prompt_does_not() -> (
    None
):  # covers: R14
    flaky = [{"id": "e", "at_min": 0, "set": {"tool.portfolio.error_rate": 0.3}}]

    def guesses(data: Dataset) -> int:
        return sum(
            1
            for c in data.conversations
            if any(not t.ok for t in c.tool_calls) and c.answer and "worth" in c.answer
        )

    assert guesses(_run(externals=flaky)) == 0
    guess = {"prompt.on_tool_error": "guess"}
    assert guesses(_run(externals=[{**flaky[0], "set": {**flaky[0]["set"], **guess}}])) > 10


def test_same_seed_same_data() -> None:  # covers: R14
    a, b = _run(), _run()
    assert a.model_dump_json() == b.model_dump_json()


def test_app_recipes_parse_and_reference_their_causes() -> None:  # covers: R14
    for path in sorted((APP / "recipes").glob("*.json")):
        r = AppRecipe.model_validate_json(path.read_text(encoding="utf-8"))
        ids = {c.id for c in r.changes} | {e.id for e in r.externals}
        assert all(f.cause in ids for f in r.faults), path.name
        assert json.loads(path.read_text(encoding="utf-8"))["id"] == path.stem
