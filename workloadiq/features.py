"""Feature builder (design doc section 8).

Collapses raw time-series into per-metric features that the detector, RCA
engine, and forecaster all consume:

- baseline mean (early window) vs recent mean (late window)
- change ratio (recent / baseline)
- recent p95
- linear trend slope per hour over the whole analyzed window
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from . import stats
from .models import MetricRecord


@dataclass
class FeatureSet:
    component_type: str
    component_name: str
    metric_name: str
    unit: str
    baseline_mean: float
    recent_mean: float
    recent_p95: float
    change_ratio: float
    slope_per_hour: float
    last_value: float
    n: int

    @property
    def key(self) -> tuple[str, str]:
        return (self.component_name, self.metric_name)


class FeatureBuilder:
    """Builds features by splitting each series into baseline and recent windows.

    baseline_frac/recent_frac are fractions of the window's *time span*: the
    first ``baseline_frac`` is baseline, the last ``recent_frac`` is recent.
    """

    def __init__(self, baseline_frac: float = 0.5, recent_frac: float = 0.25):
        if baseline_frac + recent_frac > 1.0:
            raise ValueError("baseline_frac + recent_frac must be <= 1.0")
        self.baseline_frac = baseline_frac
        self.recent_frac = recent_frac

    def build(self, records: list[MetricRecord]) -> dict[tuple[str, str], FeatureSet]:
        if not records:
            return {}

        # group by (component_name, metric_name)
        series: dict[tuple[str, str], list[MetricRecord]] = defaultdict(list)
        for r in records:
            series[(r.component_name, r.metric_name)].append(r)

        t_min = min(r.timestamp for r in records)
        t_max = max(r.timestamp for r in records)
        span = (t_max - t_min).total_seconds()
        baseline_cut = t_min.timestamp() + span * self.baseline_frac
        recent_cut = t_min.timestamp() + span * (1.0 - self.recent_frac)

        features: dict[tuple[str, str], FeatureSet] = {}
        for key, recs in series.items():
            recs.sort(key=lambda r: r.timestamp)
            base_vals = [r.metric_value for r in recs if r.timestamp.timestamp() <= baseline_cut]
            recent_vals = [r.metric_value for r in recs if r.timestamp.timestamp() >= recent_cut]
            all_vals = [r.metric_value for r in recs]

            # Fallbacks if a window is empty (very short series).
            if not base_vals:
                base_vals = all_vals[: max(1, len(all_vals) // 2)]
            if not recent_vals:
                recent_vals = all_vals[-max(1, len(all_vals) // 2):]

            base_mean = stats.mean(base_vals)
            recent_mean = stats.mean(recent_vals)

            hours = [(r.timestamp - t_min).total_seconds() / 3600.0 for r in recs]
            slope, _ = stats.linreg(hours, all_vals)

            features[key] = FeatureSet(
                component_type=recs[0].component_type.value,
                component_name=recs[0].component_name,
                metric_name=recs[0].metric_name,
                unit=recs[0].unit,
                baseline_mean=base_mean,
                recent_mean=recent_mean,
                recent_p95=stats.p95(recent_vals),
                change_ratio=stats.safe_ratio(recent_mean, base_mean),
                slope_per_hour=slope,
                last_value=recs[-1].metric_value,
                n=len(recs),
            )
        return features


def get(
    features: dict[tuple[str, str], FeatureSet],
    metric_name: str,
    component_name: str | None = None,
) -> FeatureSet | None:
    """Look up a feature by metric, optionally pinned to a component."""
    if component_name is not None:
        return features.get((component_name, metric_name))
    for (comp, metric), fs in features.items():
        if metric == metric_name:
            return fs
    return None
