"""The imported RCAEval slice (real telemetry) and the importer's conversion rules."""

import asyncio
import json
import sys
from pathlib import Path

import pytest

from eval.validate import validate
from incident.models import Dataset

ROOT = Path(__file__).resolve().parents[2]
CASES = sorted((ROOT / "scenarios" / "rcaeval").glob("rca_*"))


@pytest.mark.parametrize("case", CASES, ids=lambda p: p.name)
def test_each_imported_case_is_solvable_through_the_tools(case: Path) -> None:  # covers: R17
    assert asyncio.run(validate(case)) == []


@pytest.mark.parametrize("case", CASES, ids=lambda p: p.name)
def test_imported_data_does_not_name_the_answer(case: Path) -> None:  # covers: R17
    data = Dataset.model_validate_json((case / "data.json").read_text("utf-8"))
    truth = json.loads((case / "truth.json").read_text("utf-8"))
    text = data.incident.text
    assert truth["faults"][0]["component"] not in text and not data.changes and not data.history
    assert truth["faults"][0]["cause_type"] not in data.model_dump_json()


def test_importer_rules() -> None:  # covers: R17
    pytest.importorskip("pyarrow")
    sys.path.insert(0, str(ROOT / "src" / "scripts"))
    from import_rcaeval import logs, metrics

    rows = [{"time": 60 + s, "svc_cpu": float(s), "svc_mem": None} for s in range(120)]
    m = metrics(rows, 60, 2)
    assert m["svc"]["cpu"] == [29.5, 89.5] and "mem" not in m["svc"]  # all-empty series dropped
    lines = [{"timestamp": "60", "container_name": "a", "message": "request failed"}] + [
        {"timestamp": "61", "container_name": "a", "message": "ok"} for _ in range(20)
    ]
    out = logs(lines)
    assert out[0].level == "ERROR" and sum(x.level == "INFO" for x in out) == 2
