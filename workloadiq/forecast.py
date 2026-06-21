"""Forecasting v0 (design doc section 10).

Intentionally simple: linear trend extrapolation to estimate whether a metric is
heading toward an operational threshold, and roughly when. The goal is risk
signaling ("backlog grows ~12%/hr, threshold in ~6h"), not precise prediction.
"""

from __future__ import annotations

from .features import FeatureSet

# Default safe ceilings per metric. None => report growth rate only.
DEFAULT_THRESHOLDS: dict[str, float] = {
    "backlog_size": 100_000,
    "oldest_unacked_age_s": 1_800,
    "job_duration_s": 1_800,
    "write_latency_ms": 1_000,
    "query_latency_ms": 1_000,
    "cpu_usage": None,  # compared against cpu_request dynamically below
}

# Only forecast metrics where a rising trend means rising risk.
RISK_METRICS = [
    "backlog_size",
    "oldest_unacked_age_s",
    "job_duration_s",
    "write_latency_ms",
    "query_latency_ms",
    "cpu_usage",
]

# Fraction of baseline slope considered "flat" — ignore tiny drifts.
MIN_GROWTH_PCT_PER_HOUR = 5.0


def _pretty_hours(hours: float) -> str:
    if hours < 1:
        return f"{hours*60:.0f} minutes"
    if hours < 48:
        return f"{hours:.1f} hours"
    return f"{hours/24:.1f} days"


def forecast(features: dict[tuple[str, str], FeatureSet]) -> list[str]:
    lines: list[str] = []
    for (comp, metric), fs in features.items():
        if metric not in RISK_METRICS:
            continue
        if fs.slope_per_hour <= 0 or fs.baseline_mean <= 0:
            continue
        growth_pct = fs.slope_per_hour / fs.baseline_mean * 100.0
        if growth_pct < MIN_GROWTH_PCT_PER_HOUR:
            continue

        # resolve threshold
        threshold = DEFAULT_THRESHOLDS.get(metric)
        if metric == "cpu_usage":
            req = features.get((comp, "cpu_request"))
            threshold = req.recent_mean if req else None

        msg = f"{fs.component_name} {metric} is growing ~{growth_pct:.0f}% per hour"
        if threshold and fs.last_value < threshold and fs.slope_per_hour > 0:
            eta = (threshold - fs.last_value) / fs.slope_per_hour
            if eta > 0:
                msg += (f". At the current rate the safe threshold "
                        f"(~{threshold:g} {fs.unit}) may be exceeded in {_pretty_hours(eta)}")
        lines.append(msg)

    # Strongest growth first.
    lines.sort(key=lambda s: s, reverse=False)
    return lines
