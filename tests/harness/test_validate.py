from pathlib import Path

import pytest

from eval.validate import validate

SCEN = Path(__file__).resolve().parents[2] / "scenarios"
DIRS = sorted(d for d in SCEN.iterdir() if (d / "truth.json").exists())


def test_there_are_at_least_ten_scenarios() -> None:  # covers: R14
    assert len(DIRS) >= 10


@pytest.mark.parametrize("scenario", DIRS, ids=lambda d: d.name)
async def test_scenario_is_valid(scenario: Path) -> None:  # covers: R14
    assert await validate(scenario) == []


async def test_validator_catches_a_broken_scenario(tmp_path: Path) -> None:  # covers: R14
    src = SCEN / "s01_bad_deploy"
    (tmp_path / "data.json").write_text((src / "data.json").read_text("utf-8"), "utf-8")
    truth = (src / "truth.json").read_text("utf-8").replace("unhandled exception", "no such text")
    (tmp_path / "truth.json").write_text(truth, "utf-8")
    assert await validate(tmp_path)  # decisive evidence no longer reachable -> flagged
