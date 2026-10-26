from pathlib import Path

import pytest

from eval import variants
from eval.validate import reachable
from incident.models import Dataset
from incident.sim.truth import Truth

SCEN = Path(__file__).resolve().parents[2] / "scenarios"
DIRS = sorted(d for d in SCEN.iterdir() if (d / "truth.json").exists())


def _load(d: Path) -> tuple[Dataset, Truth]:
    return (
        Dataset.model_validate_json((d / "data.json").read_text("utf-8")),
        Truth.model_validate_json((d / "truth.json").read_text("utf-8")),
    )


@pytest.mark.parametrize("name", ["shift", "rename", "shuffle", "herring"])
@pytest.mark.parametrize("scenario", DIRS, ids=lambda d: d.name)
async def test_invariant_variants_keep_the_answer_reachable(
    scenario: Path, name: str
) -> None:  # covers: R17
    data, truth = _load(scenario)
    v_data, v_truth = variants.apply(name, data, truth)
    assert v_truth.answerable == truth.answerable
    for fault in v_truth.faults:
        for sel in fault.decisive:
            assert await reachable(v_data, sel) == truth.answerable, (fault.id, sel.contains)


@pytest.mark.parametrize("scenario", DIRS, ids=lambda d: d.name)
async def test_drop_removes_the_decisive_evidence(scenario: Path) -> None:  # covers: R13, R17
    data, truth = _load(scenario)
    v_data, v_truth = variants.apply("drop", data, truth)
    assert v_truth.expected_status == "INCONCLUSIVE" and not v_truth.answerable
    for fault in v_truth.faults:
        for sel in fault.decisive:
            assert not await reachable(v_data, sel), (fault.id, sel.contains)


def test_rename_changes_every_name_and_nothing_else() -> None:  # covers: R17
    data, truth = _load(SCEN / "s02_pool_vs_deploy")
    v, t = variants.apply("rename", data, truth)
    assert all(s.endswith("-prod") for s in v.topology.services)
    assert t.faults[0].component == "aa-sync-prod" and "aa-sync-prod" in v.metrics
    assert len(v.logs) == len(data.logs) and v.minutes == data.minutes


def test_shift_moves_clock_times_in_the_incident_text() -> None:  # covers: R17
    data, truth = _load(SCEN / "s01_bad_deploy")
    v, _ = variants.apply("shift", data, truth)
    assert "13:10" in data.incident.text and "13:10" not in v.incident.text
    assert v.logs[0].ts - data.logs[0].ts == variants.SHIFT


def test_herring_adds_an_unrelated_deploy_before_onset() -> None:  # covers: R17
    data, truth = _load(SCEN / "s02_pool_vs_deploy")
    v, _ = variants.apply("herring", data, truth)
    extra = [c for c in v.changes if c.ref.endswith("-99999")]
    assert len(extra) == 1 and extra[0].service not in {"aa-sync", "postgres", "portfolio-consumer"}
    assert len(v.changes) == len(data.changes) + 1
