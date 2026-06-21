"""End-to-end RCA loop: telemetry -> features -> detect -> RCA -> forecast -> result.

This is the single entry point callers (CLI, tests, future API) use.
"""

from __future__ import annotations

from .detect import Detector, select_symptom
from .features import FeatureBuilder
from .forecast import forecast as run_forecast
from .models import MetricRecord, Pipeline, RCAResult, Severity
from .rca import RCAEngine, severity_from_signals
from .recommend import recommend


def analyze_pipeline(
    pipeline: Pipeline,
    records: list[MetricRecord],
    baseline_frac: float = 0.5,
    recent_frac: float = 0.25,
    up_threshold: float = 1.5,
) -> RCAResult:
    if not records:
        raise ValueError("no telemetry records to analyze")

    start = min(r.timestamp for r in records)
    end = max(r.timestamp for r in records)

    features = FeatureBuilder(baseline_frac, recent_frac).build(records)
    signals = Detector(up_threshold=up_threshold).detect(features)
    symptom = select_symptom(signals)

    verdict = RCAEngine(features, pipeline).rank()
    severity = severity_from_signals(signals, verdict["is_incident"])

    # Evidence: rule evidence first, then top contextual signals not already named.
    evidence = list(verdict["evidence"])
    seen = " ".join(evidence).lower()
    for s in signals[:5]:
        frag = f"{s.component_name} {s.metric_name}".lower()
        if frag not in seen:
            evidence.append(s.describe())
            seen += " " + frag
    if not evidence:
        evidence = ["No metric deviated significantly from baseline"]

    recommendations = recommend(verdict["root_cause"]) if verdict["is_incident"] or \
        "over-provisioning" in verdict["root_cause"].lower() else []

    incident_id = f"inc-{pipeline.pipeline_id}-{int(start.timestamp())}"

    return RCAResult(
        incident_id=incident_id,
        pipeline_id=pipeline.pipeline_id,
        start_time=start,
        end_time=end,
        symptom=symptom,
        root_cause=verdict["root_cause"],
        confidence=verdict["confidence"],
        evidence=evidence,
        recommendations=recommendations,
        severity=severity,
        ranked_causes=verdict["ranked"],
        forecasts=run_forecast(features),
    )
