"""Convert RCAEval RE2 cases (real telemetry from fault injection) into our Dataset + answer key.

Usage (needs pyarrow): python scripts/import_rcaeval.py RAW_DIR OUT_DIR CASE [CASE ...]
RAW_DIR holds cases.parquet and one folder per case with inject_time.txt, metrics.parquet and
logs.parquet (from huggingface.co/datasets/phamquiluan/RCAEval). Traces are not used (our tools
have no trace query). Conversion is the same for every case:
* metrics: per-second series averaged per minute, `<service>_<metric>` -> metrics[service][metric]
* logs: level inferred from the message (error/exception/fail -> ERROR, warn/retry -> WARN, else
  INFO); every WARN/ERROR line kept, INFO lines sampled 1 in 10 to keep the store small
* topology: the published Online Boutique call graph (not derived from the fault)
* incident text: one generic symptom report for every case, with the injection minute as "since"
* answer key: root-cause service and fault type from cases.parquet; decisive evidence is the
  fault's own metric on the root service exceeding 1.2x its pre-fault maximum (if it does not, the
  validator reports the case as not solvable through our tools)
No changes and no past incidents exist in RCAEval, so those tools return nothing.
"""

import re
import sys
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from incident.models import Dataset, Edge, Incident, LogLine, Topology
from incident.sim.truth import Selector, Truth, TruthFault

OB_EDGES = [
    ("frontend", "adservice"), ("frontend", "cartservice"), ("frontend", "checkoutservice"),
    ("frontend", "currencyservice"), ("frontend", "productcatalogservice"),
    ("frontend", "recommendationservice"), ("frontend", "shippingservice"),
    ("checkoutservice", "cartservice"), ("checkoutservice", "currencyservice"),
    ("checkoutservice", "emailservice"), ("checkoutservice", "paymentservice"),
    ("checkoutservice", "productcatalogservice"), ("checkoutservice", "shippingservice"),
    ("recommendationservice", "productcatalogservice"), ("cartservice", "redis"),
]  # fmt: skip
FAULT_METRIC = {"cpu": "cpu", "mem": "mem", "disk": "diskio", "socket": "socket",
                "delay": "latency-90", "loss": "latency-90"}  # fmt: skip
CAUSE = {"cpu": "cpu_saturation", "mem": "memory_exhaustion", "disk": "disk_io_saturation",
         "socket": "socket_exhaustion", "delay": "network_delay",
         "loss": "network_packet_loss"}  # fmt: skip
ERROR = re.compile(r"error|exception|fail|refused|timed? ?out", re.I)
WARN = re.compile(r"warn|retry|slow|unavailable", re.I)
TEXT = "Shop users report slow pages and some failed requests since about {at:%H:%M} UTC."


def _ts(sec: Any) -> datetime:
    return datetime.fromtimestamp(int(float(sec)), UTC)


def metrics(rows: list[dict[str, Any]], t0: int, minutes: int) -> dict[str, dict[str, list]]:
    acc: dict[str, dict[str, list[list[float]]]] = defaultdict(dict)
    for r in rows:
        m = (int(r["time"]) - t0) // 60
        if not 0 <= m < minutes:
            continue
        for col, v in r.items():
            if col == "time" or v is None or v != v or "_" not in col:
                continue
            svc, name = col.split("_", 1)
            acc[svc].setdefault(name, [[] for _ in range(minutes)])[m].append(float(v))
    return {
        svc: {k: [round(sum(b) / len(b), 4) if b else None for b in v] for k, v in ms.items()}
        for svc, ms in acc.items()
    }


def logs(rows: list[dict[str, Any]]) -> list[LogLine]:
    out, info = [], 0
    for r in rows:
        msg = str(r["message"])[:400]
        level = "ERROR" if ERROR.search(msg) else "WARN" if WARN.search(msg) else "INFO"
        if level == "INFO":
            info += 1
            if info % 10:
                continue
        svc = str(r["container_name"])
        out.append(LogLine(ts=_ts(r["timestamp"]), service=svc, host=svc, level=level, msg=msg))
    return sorted(out, key=lambda x: x.ts)


def convert(raw: Path, case: dict[str, Any]) -> tuple[Dataset, Truth]:
    d = raw / case["case"]
    t0, inject = int(case["time_start"]), int((d / "inject_time.txt").read_text().strip())
    minutes = (int(case["time_end"]) - t0) // 60 + 1
    series = metrics(pq.read_table(d / "metrics.parquet").to_pylist(), t0, minutes)
    services = sorted({*series, *(s for e in OB_EDGES for s in e)})
    start, at = _ts(t0), _ts(inject)
    data = Dataset(
        incident=Incident(reported_at=at + timedelta(minutes=8), text=TEXT.format(at=at)),
        start=start, minutes=minutes,
        topology=Topology(services=services, queues=[],
                          edges=[Edge(caller=a, callee=b, weight=0.5) for a, b in OB_EDGES]),
        logs=logs(pq.read_table(d / "logs.parquet").to_pylist()), metrics=series,
        changes=[], history=[], tool_faults=[],
    )  # fmt: skip
    return data, truth(case, series, start, at, minutes)


def truth(case: dict[str, Any], series: dict[str, Any], start: datetime, at: datetime,
          minutes: int) -> Truth:  # fmt: skip
    svc, fault = case["root_cause_service"], case["fault"]
    metric = FAULT_METRIC[fault]
    onset = int((at - start).total_seconds() // 60)
    before = [v for v in series.get(svc, {}).get(metric, [])[:onset] if v is not None]
    sel = Selector(
        kind="metric", service=svc, metric=metric, min_value=round(1.2 * max(before or [0]), 4),
        start=at, end=start + timedelta(minutes=minutes),
    )  # fmt: skip
    f = TruthFault(
        id="F1", role="primary", component=svc, cause_type=CAUSE[fault],
        description=f"{case['fault_description']} injected into {svc} ({case['dataset']}).",
        onset=at, decisive=[sel],
    )  # fmt: skip
    trap = (f"real telemetry ({case['dataset']}, {case['fault_description']}); no change events, "
            "no past incidents, per-second data averaged per minute")  # fmt: skip
    return Truth(faults=[f], answerable=True, expected_status="ANSWER", trap=trap)


def main(raw: Path, out: Path, names: list[str]) -> None:
    index = {c["case"]: c for c in pq.read_table(raw / "cases.parquet").to_pylist()}
    for name in names:
        data, t = convert(raw, index[name])
        d = out / f"rca_{name}"
        d.mkdir(parents=True, exist_ok=True)
        (d / "data.json").write_text(data.model_dump_json(exclude_none=True), "utf-8")
        (d / "truth.json").write_text(t.model_dump_json(indent=2), "utf-8")
        print(f"{d.name}: {len(data.logs)} logs, {data.minutes} min, {len(data.metrics)} services")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3:])
