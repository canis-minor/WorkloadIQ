"""Synthetic telemetry generator.

Produces realistic-looking ``MetricRecord`` streams for known failure modes so
the full RCA loop can be exercised without live GCP. Each scenario is a flat
spec of per-metric (baseline_value -> incident_value); the generator ramps the
metric across the incident window and adds deterministic noise.

Determinism: noise comes from a seeded ``random.Random`` so runs are
reproducible (the workflow/runtime forbids unseeded randomness anyway).
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from ..models import ComponentType, MetricRecord, Pipeline, Sink, SinkType, Worker


@dataclass
class MetricSpec:
    component_type: ComponentType
    component_name: str
    metric_name: str
    unit: str
    baseline: float
    incident: float  # value reached at the end of the incident ramp
    noise: float = 0.05  # fractional gaussian noise


# A pipeline topology shared by the scenarios below.
def _default_pipeline(pipeline_id: str, sink_name: str, sink_type: SinkType) -> Pipeline:
    return Pipeline(
        pipeline_id=pipeline_id,
        pipeline_name=pipeline_id,
        queue="pubsub",
        workers=[Worker(worker_name="worker", worker_type="cpu")],
        sinks=[Sink(sink_name=sink_name, sink_type=sink_type)],
        owner="data-platform",
        region="us-central1",
    )


# Canonical metric names used everywhere (features/RCA reference these).
def _base_specs(sink_name: str) -> dict[str, MetricSpec]:
    """A healthy baseline for every metric; scenarios override a few entries."""
    q = ComponentType.QUEUE
    w = ComponentType.WORKER
    s = ComponentType.SINK
    specs = [
        # queue
        MetricSpec(q, "pubsub", "publish_rate", "msg/s", 500, 500),
        MetricSpec(q, "pubsub", "ack_rate", "msg/s", 500, 500),
        MetricSpec(q, "pubsub", "backlog_size", "msg", 2000, 2000, 0.10),
        MetricSpec(q, "pubsub", "oldest_unacked_age_s", "s", 30, 30, 0.10),
        MetricSpec(q, "pubsub", "redelivery_count", "count", 5, 5, 0.20),
        MetricSpec(q, "pubsub", "dead_letter_count", "count", 0, 0, 0.0),
        # worker
        MetricSpec(w, "worker", "cpu_request", "cores", 4, 4, 0.0),
        MetricSpec(w, "worker", "cpu_usage", "cores", 1.6, 1.6, 0.08),
        MetricSpec(w, "worker", "mem_request", "GiB", 8, 8, 0.0),
        MetricSpec(w, "worker", "mem_usage", "GiB", 3.5, 3.5, 0.08),
        MetricSpec(w, "worker", "job_duration_s", "s", 120, 120, 0.08),
        MetricSpec(w, "worker", "failure_rate", "ratio", 0.01, 0.01, 0.30),
        MetricSpec(w, "worker", "retry_count", "count", 5, 5, 0.25),
        MetricSpec(w, "worker", "throughput", "rec/s", 480, 480, 0.05),
        MetricSpec(w, "worker", "concurrency", "count", 10, 10, 0.0),
        MetricSpec(w, "worker", "pod_restart_count", "count", 0, 0, 0.0),
        # sink
        MetricSpec(s, sink_name, "write_latency_ms", "ms", 50, 50, 0.10),
        MetricSpec(s, sink_name, "error_rate", "ratio", 0.005, 0.005, 0.30),
        MetricSpec(s, sink_name, "throttling_rate", "ratio", 0.0, 0.0, 0.0),
        MetricSpec(s, sink_name, "query_latency_ms", "ms", 80, 80, 0.10),
    ]
    return {sp.metric_name + "@" + sp.component_name: sp for sp in specs}


def _apply(base: dict[str, MetricSpec], component: str, **overrides: tuple) -> None:
    """Override (incident,[noise]) for metrics on a component, in place."""
    for metric, val in overrides.items():
        key = metric + "@" + component
        sp = base[key]
        if isinstance(val, tuple):
            sp.incident = val[0]
            if len(val) > 1:
                sp.noise = val[1]
        else:
            sp.incident = val


def _scenario_specs(scenario: str) -> tuple[dict[str, MetricSpec], str, SinkType, str]:
    """Returns (specs, sink_name, sink_type, symptom_hint)."""
    if scenario == "bigquery_bottleneck":
        base = _base_specs("bigquery")
        # Sink latency spikes 8x first; job duration follows; CPU/backlog stable.
        _apply(base, "bigquery", write_latency_ms=(400, 0.12))
        _apply(base, "worker", job_duration_s=(840, 0.10), retry_count=(12, 0.25),
               throughput=(430, 0.06))
        return base, "bigquery", SinkType.BIGQUERY, "End-to-end latency increased"

    if scenario == "compute_bottleneck":
        base = _base_specs("bigquery")
        # CPU saturates, job duration up, backlog grows after saturation.
        _apply(base, "worker", cpu_usage=(3.9, 0.05), mem_usage=(7.6, 0.06),
               job_duration_s=(600, 0.10), throughput=(300, 0.08),
               pod_restart_count=(3, 0.0))
        _apply(base, "pubsub", backlog_size=(45000, 0.12),
               oldest_unacked_age_s=(420, 0.12))
        return base, "bigquery", SinkType.BIGQUERY, "End-to-end latency increased"

    if scenario == "queue_bottleneck":
        base = _base_specs("bigquery")
        # Backlog & age grow, throughput flat, sinks fine. Publish outpaces ack.
        _apply(base, "pubsub", backlog_size=(80000, 0.12),
               oldest_unacked_age_s=(900, 0.12), publish_rate=(900,),
               ack_rate=(500,))
        return base, "bigquery", SinkType.BIGQUERY, "Pub/Sub backlog growing"

    if scenario == "retry_storm":
        base = _base_specs("bigquery")
        # Failures & retries spike, CPU up, throughput does NOT rise proportionally.
        _apply(base, "worker", failure_rate=(0.18, 0.20), retry_count=(140, 0.20),
               cpu_usage=(3.4, 0.06), throughput=(360, 0.08))
        _apply(base, "pubsub", redelivery_count=(120, 0.20), dead_letter_count=(40, 0.20))
        return base, "bigquery", SinkType.BIGQUERY, "Failure rate increased"

    if scenario == "over_provisioning":
        base = _base_specs("bigquery")
        # Steady & healthy, but requests dwarf usage. Flat-high (no ramp): set
        # baseline and incident equal so it reads as a standing efficiency issue.
        for metric, value in {"cpu_request": 16.0, "cpu_usage": 1.5,
                              "mem_request": 32.0, "mem_usage": 3.0}.items():
            sp = base[metric + "@worker"]
            sp.baseline = value
            sp.incident = value
        return base, "bigquery", SinkType.BIGQUERY, "Resource efficiency review"

    if scenario == "healthy":
        return _base_specs("bigquery"), "bigquery", SinkType.BIGQUERY, "No degradation"

    raise ValueError(f"unknown scenario: {scenario!r}. See SCENARIOS.")


SCENARIOS = [
    "bigquery_bottleneck",
    "compute_bottleneck",
    "queue_bottleneck",
    "retry_storm",
    "over_provisioning",
    "healthy",
]


def generate(
    scenario: str,
    pipeline_id: str = "pipeline_a",
    hours: float = 3.0,
    step_seconds: int = 60,
    end: datetime | None = None,
    incident_start_frac: float = 0.5,
    seed: int = 7,
) -> tuple[Pipeline, list[MetricRecord]]:
    """Generate one scenario's telemetry.

    The first ``incident_start_frac`` of the window is baseline; the metric then
    ramps linearly toward its incident value over the remainder.
    """
    specs, sink_name, sink_type, _symptom = _scenario_specs(scenario)
    pipeline = _default_pipeline(pipeline_id, sink_name, sink_type)
    rng = random.Random(seed)

    if end is None:
        end = datetime.now(timezone.utc).replace(microsecond=0)
    n_steps = max(2, int(hours * 3600 / step_seconds))
    start = end - timedelta(seconds=step_seconds * (n_steps - 1))

    records: list[MetricRecord] = []
    for i in range(n_steps):
        ts = start + timedelta(seconds=step_seconds * i)
        frac = i / (n_steps - 1)
        # ramp factor in [0,1]: 0 during baseline, rising to 1 at window end.
        if frac <= incident_start_frac:
            ramp = 0.0
        else:
            ramp = (frac - incident_start_frac) / (1 - incident_start_frac)

        for sp in specs.values():
            value = sp.baseline + (sp.incident - sp.baseline) * ramp
            if sp.noise:
                value *= 1 + rng.gauss(0, sp.noise)
            value = max(0.0, value)
            records.append(
                MetricRecord(
                    timestamp=ts,
                    pipeline_id=pipeline_id,
                    component_type=sp.component_type,
                    component_name=sp.component_name,
                    metric_name=sp.metric_name,
                    metric_value=round(value, 4),
                    unit=sp.unit,
                    labels={"scenario": scenario},
                )
            )
    return pipeline, records
