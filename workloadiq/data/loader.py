"""Load and persist normalized telemetry (CSV / JSON) and pipeline configs.

CSV is the canonical interchange format — one row per ``MetricRecord`` — so
real GCP collectors added later just need to emit the same columns.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from ..models import ComponentType, MetricRecord, Pipeline, Sink, SinkType, Worker

CSV_FIELDS = [
    "timestamp",
    "pipeline_id",
    "component_type",
    "component_name",
    "metric_name",
    "metric_value",
    "unit",
    "labels",
]


def _parse_ts(raw: str) -> datetime:
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def write_csv(records: list[MetricRecord], path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for r in records:
            writer.writerow(
                {
                    "timestamp": r.timestamp.isoformat(),
                    "pipeline_id": r.pipeline_id,
                    "component_type": r.component_type.value,
                    "component_name": r.component_name,
                    "metric_name": r.metric_name,
                    "metric_value": r.metric_value,
                    "unit": r.unit,
                    "labels": json.dumps(r.labels, separators=(",", ":")),
                }
            )


def read_csv(path: str | Path) -> list[MetricRecord]:
    path = Path(path)
    records: list[MetricRecord] = []
    with path.open(newline="") as fh:
        for row in csv.DictReader(fh):
            labels_raw = row.get("labels") or "{}"
            try:
                labels = json.loads(labels_raw)
            except json.JSONDecodeError:
                labels = {}
            records.append(
                MetricRecord(
                    timestamp=_parse_ts(row["timestamp"]),
                    pipeline_id=row["pipeline_id"],
                    component_type=ComponentType(row["component_type"]),
                    component_name=row["component_name"],
                    metric_name=row["metric_name"],
                    metric_value=float(row["metric_value"]),
                    unit=row.get("unit", ""),
                    labels=labels,
                )
            )
    return records


def read_telemetry(path: str | Path) -> list[MetricRecord]:
    """Load telemetry from .csv or .json (list of row dicts)."""
    path = Path(path)
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text())
        records = []
        for row in data:
            records.append(
                MetricRecord(
                    timestamp=_parse_ts(row["timestamp"]),
                    pipeline_id=row["pipeline_id"],
                    component_type=ComponentType(row["component_type"]),
                    component_name=row["component_name"],
                    metric_name=row["metric_name"],
                    metric_value=float(row["metric_value"]),
                    unit=row.get("unit", ""),
                    labels=row.get("labels", {}) or {},
                )
            )
        return records
    return read_csv(path)


def write_pipeline(pipeline: Pipeline, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "pipeline_id": pipeline.pipeline_id,
        "pipeline_name": pipeline.pipeline_name,
        "queue": pipeline.queue,
        "workers": [{"worker_name": w.worker_name, "worker_type": w.worker_type} for w in pipeline.workers],
        "sinks": [{"sink_name": s.sink_name, "sink_type": s.sink_type.value} for s in pipeline.sinks],
        "owner": pipeline.owner,
        "region": pipeline.region,
    }
    path.write_text(json.dumps(payload, indent=2))


def read_pipeline(path: str | Path) -> Pipeline:
    data = json.loads(Path(path).read_text())
    return Pipeline(
        pipeline_id=data["pipeline_id"],
        pipeline_name=data.get("pipeline_name", data["pipeline_id"]),
        queue=data.get("queue", "pubsub"),
        workers=[Worker(w["worker_name"], w.get("worker_type", "cpu")) for w in data.get("workers", [])],
        sinks=[Sink(s["sink_name"], SinkType(s["sink_type"])) for s in data.get("sinks", [])],
        owner=data.get("owner", ""),
        region=data.get("region", ""),
    )
