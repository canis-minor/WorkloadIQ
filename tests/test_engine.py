import pytest

from workloadiq.data import generator
from workloadiq.engine import analyze_pipeline
from workloadiq.models import Severity

# (scenario, expected substring in root_cause)
CASES = [
    ("bigquery_bottleneck", "bigquery"),
    ("compute_bottleneck", "compute saturation"),
    ("queue_bottleneck", "queue backlog"),
    ("retry_storm", "retry storm"),
    ("over_provisioning", "over-provisioning"),
]


@pytest.mark.parametrize("scenario,needle", CASES)
def test_root_cause_classification(scenario, needle):
    pipeline, records = generator.generate(scenario=scenario, hours=3)
    result = analyze_pipeline(pipeline, records)
    assert needle in result.root_cause.lower(), (scenario, result.root_cause)


def test_healthy_reports_no_degradation():
    pipeline, records = generator.generate(scenario="healthy", hours=3)
    result = analyze_pipeline(pipeline, records)
    assert "no significant degradation" in result.root_cause.lower()
    assert result.severity == Severity.LOW


def test_incident_has_evidence_and_recommendations():
    pipeline, records = generator.generate(scenario="bigquery_bottleneck", hours=3)
    result = analyze_pipeline(pipeline, records)
    assert result.evidence
    assert result.recommendations
    assert 0.0 <= result.confidence <= 0.95
    assert result.severity == Severity.HIGH


def test_bigquery_scenario_forecasts_risk():
    pipeline, records = generator.generate(scenario="bigquery_bottleneck", hours=3)
    result = analyze_pipeline(pipeline, records)
    assert result.forecasts  # rising latency/duration should produce risk lines


def test_empty_records_raises():
    pipeline, _ = generator.generate(scenario="healthy", hours=3)
    with pytest.raises(ValueError):
        analyze_pipeline(pipeline, [])
