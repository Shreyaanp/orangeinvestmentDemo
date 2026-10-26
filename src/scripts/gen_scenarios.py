"""Generate scenarios/<id>/{data,truth}.json from scenarios/recipes/*.json (service-level suite)
and scenarios/app/recipes/*.json (event-level application suite).

Usage: python scripts/gen_scenarios.py [scenario_id ...]
"""

import sys
from pathlib import Path

from incident.models import Dataset
from incident.sim.app.build import load_world as load_app
from incident.sim.app.build import simulate_app
from incident.sim.app.spec import AppRecipe
from incident.sim.engine import simulate
from incident.sim.recipe import Recipe
from incident.sim.truth import Truth
from incident.sim.world import load_world

ROOT = Path(__file__).resolve().parents[2]
SCEN = ROOT / "scenarios"


def _write(rid: str, data: Dataset, truth: Truth) -> None:
    out = SCEN / rid
    out.mkdir(parents=True, exist_ok=True)
    (out / "data.json").write_text(data.model_dump_json(exclude_none=True), encoding="utf-8")
    (out / "truth.json").write_text(truth.model_dump_json(indent=2), encoding="utf-8")
    extra = f", {len(data.conversations)} conversations" if data.conversations else ""
    print(f"{rid}: {len(data.logs)} logs, {len(data.changes)} changes{extra}")


def main(only: list[str]) -> None:
    world = load_world(SCEN / "world.json")
    for path in sorted((SCEN / "recipes").glob("*.json")):
        recipe = Recipe.model_validate_json(path.read_text(encoding="utf-8"))
        if not only or recipe.id in only:
            _write(recipe.id, *simulate(world, recipe))
    app_world, tree = load_app(SCEN / "app")
    for path in sorted((SCEN / "app" / "recipes").glob("*.json")):
        app = AppRecipe.model_validate_json(path.read_text(encoding="utf-8"))
        if not only or app.id in only:
            _write(app.id, *simulate_app(app_world, tree, app))


if __name__ == "__main__":
    main(sys.argv[1:])
