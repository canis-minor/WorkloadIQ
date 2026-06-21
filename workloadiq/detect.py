"""Anomaly + trend detector (design doc section 8).

Turns features into a list of significant *signals* (a metric moved up or down
beyond a threshold). Signals feed both symptom selection and the RCA engine.
"""

from __future__ import annotations

from dataclasses import dataclass

from .features import FeatureSet

# Metrics where an *increase* is the concerning direction.
INCREASE_IS_BAD = {
    "backlog_size",
    "oldest_unacked_age_s",
    "ack_latency_ms",
    "redelivery_count",
    "dead_letter_count",
    "job_duration_s",
    "failure_rate",
    "retry_count",
    "pod_restart_count",
    "queue_time_s",
    "write_latency_ms",
    "read_latency_ms",
    "error_rate",
    "throttling_rate",
    "query_latency_ms",
    "mutation_latency_ms",
    "indexing_latency_ms",
    "cpu_usage",
    "mem_usage",
}


@dataclass
class Signal:
    component_type: str
    component_name: str
    metric_name: str
    direction: str  # "up" | "down"
    change_ratio: float
    recent_mean: float
    baseline_mean: float
    unit: str

    @property
    def pct_change(self) -> float:
        return (self.change_ratio - 1.0) * 100.0

    def describe(self) -> str:
        if self.change_ratio == float("inf"):
            return f"{self.component_name} {self.metric_name} appeared (was ~0)"
        factor = self.change_ratio if self.direction == "up" else (
            1.0 / self.change_ratio if self.change_ratio else 0.0
        )
        return (
            f"{self.component_name} {self.metric_name} {self.direction} "
            f"{factor:.1f}x ({self.baseline_mean:.3g} -> {self.recent_mean:.3g} {self.unit})".strip()
        )


class Detector:
    """Flags metrics whose recent window deviates from baseline beyond a factor."""

    def __init__(self, up_threshold: float = 1.5, down_threshold: float = 0.66):
        self.up_threshold = up_threshold
        self.down_threshold = down_threshold

    def detect(self, features: dict[tuple[str, str], FeatureSet]) -> list[Signal]:
        signals: list[Signal] = []
        for fs in features.values():
            cr = fs.change_ratio
            direction = None
            if cr >= self.up_threshold or cr == float("inf"):
                direction = "up"
            elif 0 < cr <= self.down_threshold:
                direction = "down"
            if direction is None:
                continue
            signals.append(
                Signal(
                    component_type=fs.component_type,
                    component_name=fs.component_name,
                    metric_name=fs.metric_name,
                    direction=direction,
                    change_ratio=cr,
                    recent_mean=fs.recent_mean,
                    baseline_mean=fs.baseline_mean,
                    unit=fs.unit,
                )
            )
        # Largest movers first.
        signals.sort(
            key=lambda s: (s.change_ratio if s.change_ratio != float("inf") else 1e9),
            reverse=True,
        )
        return signals


# Symptom selection: which top-level user-visible problem to report.
# Ordered by how directly each metric maps to an end-user symptom.
_SYMPTOM_PRIORITY = [
    ("job_duration_s", "End-to-end latency increased"),
    ("backlog_size", "Pub/Sub backlog growing"),
    ("failure_rate", "Failure rate increased"),
    ("write_latency_ms", "Downstream write latency increased"),
    ("query_latency_ms", "Downstream query latency increased"),
]


def select_symptom(signals: list[Signal]) -> str:
    up = {s.metric_name for s in signals if s.direction == "up"}
    for metric, symptom in _SYMPTOM_PRIORITY:
        if metric in up:
            return symptom
    if signals:
        return f"Anomaly in {signals[0].component_name} {signals[0].metric_name}"
    return "No degradation detected"
