"""Core data model for WorkloadIQ (design doc section 7).

Everything downstream — features, detection, RCA, forecasting, reporting —
operates on these normalized types so collectors (synthetic now, real GCP
later) only need to emit ``MetricRecord`` rows in a common schema.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class ComponentType(str, Enum):
    QUEUE = "queue"
    WORKER = "worker"
    SINK = "sink"


class SinkType(str, Enum):
    BIGQUERY = "bigquery"
    BIGTABLE = "bigtable"
    ELASTICSEARCH = "elasticsearch"


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class Worker:
    worker_name: str
    worker_type: str = "cpu"


@dataclass(frozen=True)
class Sink:
    sink_name: str
    sink_type: SinkType


@dataclass
class Pipeline:
    """Topology of one event-driven pipeline (the dependency graph for RCA)."""

    pipeline_id: str
    pipeline_name: str
    queue: str
    workers: list[Worker] = field(default_factory=list)
    sinks: list[Sink] = field(default_factory=list)
    owner: str = ""
    region: str = ""


@dataclass
class MetricRecord:
    """A single normalized time-series sample.

    This is the universal interchange row: one timestamp, one metric, one value.
    """

    timestamp: datetime
    pipeline_id: str
    component_type: ComponentType
    component_name: str
    metric_name: str
    metric_value: float
    unit: str = ""
    labels: dict[str, str] = field(default_factory=dict)


@dataclass
class RCAResult:
    """Output of the RCA engine for one incident window (design doc section 7)."""

    incident_id: str
    pipeline_id: str
    start_time: datetime
    end_time: datetime
    symptom: str
    root_cause: str
    confidence: float
    evidence: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    severity: Severity = Severity.LOW
    # Ranked alternative causes considered: list of (cause, score) for transparency.
    ranked_causes: list[tuple[str, float]] = field(default_factory=list)
    # Forward-looking risk lines from the forecaster.
    forecasts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "incident_id": self.incident_id,
            "pipeline_id": self.pipeline_id,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "symptom": self.symptom,
            "root_cause": self.root_cause,
            "confidence": round(self.confidence, 2),
            "severity": self.severity.value,
            "evidence": list(self.evidence),
            "recommendations": list(self.recommendations),
            "ranked_causes": [
                {"cause": c, "score": round(s, 3)} for c, s in self.ranked_causes
            ],
            "forecasts": list(self.forecasts),
        }
