"""Recommendation generator (design doc sections 9 & 11).

Maps a root-cause label to concrete, human-readable next actions. Keyed by
substrings so sink-specific labels (e.g. "BigQuery write bottleneck") resolve to
the right advice.
"""

from __future__ import annotations

_RECS: list[tuple[str, list[str]]] = [
    ("bigquery", [
        "Check BigQuery quota, slot reservations, and job concurrency",
        "Inspect recent schema or partition/clustering changes",
        "Review write batch size and load-job vs streaming-insert behavior",
        "Add temporary throttling or buffering if backlog begins to grow",
    ]),
    ("bigtable", [
        "Check for hotspotting and row-key distribution",
        "Inspect mutation latency and instance node CPU utilization",
        "Consider adding nodes or rebalancing tablets",
        "Review batch mutation size and retry policy",
    ]),
    ("elasticsearch", [
        "Check indexing latency, shard health, and rejected writes (bulk queue)",
        "Tune refresh interval and bulk request size",
        "Review shard count / hot node balance",
        "Inspect mapping or analyzer changes that increased indexing cost",
    ]),
    ("queue backlog", [
        "Increase worker concurrency or replica count to raise ack rate",
        "Check whether publish rate spiked or ack rate dropped",
        "Verify subscriber health and ack deadline configuration",
        "Confirm downstream sinks are not back-pressuring the workers",
    ]),
    ("compute saturation", [
        "Increase worker concurrency or CPU/memory requests",
        "Inspect recent code or dependency changes that increased job duration",
        "Profile the hot path; check for added synchronous work",
        "Scale horizontally if per-job CPU is genuinely needed",
    ]),
    ("retry storm", [
        "Inspect recent error types and whether failures are deterministic",
        "Review retry policy (backoff, max attempts) and dead-letter behavior",
        "Check for a recent deploy or upstream dependency change",
        "Stop retrying non-retryable errors to reclaim wasted CPU",
    ]),
    ("over-provisioning", [
        "Reduce CPU request toward p95 usage (keep headroom) for affected jobs",
        "Reduce memory request toward p95 usage for affected jobs",
        "Re-evaluate after a full traffic cycle to avoid under-provisioning peaks",
    ]),
]

_DEFAULT = [
    "Correlate the moved metrics across queue, compute, and sink in this window",
    "Check for a recent deployment or configuration change at the onset time",
]


def recommend(root_cause: str) -> list[str]:
    rc = root_cause.lower()
    for needle, recs in _RECS:
        if needle in rc:
            return list(recs)
    return list(_DEFAULT)
