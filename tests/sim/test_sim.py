import json
from pathlib import Path

import pytest

from incident.models import Dataset
from incident.sim.engine import simulate
from incident.sim.recipe import Recipe
from incident.sim.truth import Selector, Truth
from incident.sim.world import load_world

SCEN = Path(__file__).resolve().parents[2] / "scenarios"
RECIPES = sorted((SCEN / "recipes").glob("*.json"))
WORLD = load_world(SCEN / "world.json")


def _run(path: Path) -> tuple[Recipe, Dataset, Truth]:
    recipe = Recipe.model_validate_json(path.read_text(encoding="utf-8"))
    data, truth = simulate(WORLD, recipe)
    return recipe, data, truth


@pytest.mark.parametrize("path", RECIPES, ids=lambda p: p.stem)
def test_deterministic(path: Path) -> None:
    a, b = _run(path), _run(path)
    assert a[1].model_dump_json() == b[1].model_dump_json()


@pytest.mark.parametrize("path", RECIPES, ids=lambda p: p.stem)
def test_decisive_evidence_exists_when_answerable(path: Path) -> None:  # covers: R14
    _, data, truth = _run(path)
    for fault in truth.faults:
        for sel in fault.decisive:
            hit = _present(data, sel)
            assert hit == truth.answerable, f"{fault.id} {sel.kind} {sel.contains!r}"


def _present(data: Dataset, sel: Selector) -> bool:
    if sel.kind == "log":
        return any(
            ln.service == sel.service
            and ln.level == sel.level
            and sel.contains in ln.msg
            and sel.start <= ln.ts < sel.end
            for ln in data.logs
        )
    if sel.kind == "change":
        return any(c.service == sel.service and sel.contains in c.ref for c in data.changes)
    assert sel.metric is not None and sel.min_value is not None
    return any(v is not None and v >= sel.min_value for v in data.metrics[sel.service][sel.metric])


@pytest.mark.parametrize("path", RECIPES, ids=lambda p: p.stem)
def test_distractors_not_in_truth(path: Path) -> None:
    recipe, _, truth = _run(path)
    ids = {f.id for f in recipe.faults if f.role == "distractor"}
    assert ids.isdisjoint({f.id for f in truth.faults})


@pytest.mark.parametrize("path", RECIPES, ids=lambda p: p.stem)
def test_dataset_does_not_leak_answer_key(path: Path) -> None:  # covers: R17
    recipe, data, truth = _run(path)
    blob = data.model_dump_json()
    assert recipe.id not in blob
    assert recipe.trap not in blob
    assert all(f.cause_type not in blob for f in truth.faults)


def test_queue_backlog_is_causal() -> None:
    _, data, _ = _run(SCEN / "recipes" / "s04_queue_backlog.json")
    m = data.metrics
    first = lambda svc, key, thr: next(  # noqa: E731
        t for t, v in enumerate(m[svc][key]) if v is not None and v > thr
    )
    cause = first("aa-sync", "latency_ms", 300)
    effect = first("portfolio-consumer", "latency_ms", 300)
    backlog = first("portfolio-updates", "depth", 100)
    assert cause < effect <= backlog
    assert max(v or 0 for v in m["portfolio-updates"]["depth"][:cause]) < 5


def test_artifacts_apply() -> None:
    recipe = Recipe.model_validate_json(
        (SCEN / "recipes" / "s01_bad_deploy.json").read_text(encoding="utf-8")
    )
    raw = json.loads(recipe.model_dump_json())
    raw["artifacts"] = [
        {"kind": "log_drop", "service": "order-router", "keep_frac": 0.0},
        {"kind": "metric_missing", "service": "order-router", "metric": "err_rate", "from_min": 60},
    ]
    data, _ = simulate(WORLD, Recipe.model_validate(raw))
    assert not [ln for ln in data.logs if ln.service == "order-router"]
    assert data.metrics["order-router"]["err_rate"][70] is None
    assert data.metrics["order-router"]["err_rate"][10] is not None
