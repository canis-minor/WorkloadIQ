# WorkloadIQ

Forecasting and root cause analysis for event-driven GCP workloads.

> Monitoring tells you *what* changed. WorkloadIQ explains *why* it changed and *what to do next*.

v0 targets a common production pattern:

```
Pub/Sub → CPU Workers / Jobs → BigQuery / Bigtable / Elasticsearch
```

It ingests normalized time-series telemetry, detects degradation, and produces a
ranked, evidence-backed root cause with recommendations and a simple risk
forecast — as a CLI report, Markdown, or JSON.

## Status

**v0** — rule-based RCA over synthetic telemetry. Pure Python standard library,
**no third-party runtime dependencies**. Real GCP collectors land in v1 (see the
[design doc](workloadiq_v0_design_doc.md), section 14).

## Install / run

No install required — run as a module:

```bash
python3 -m workloadiq --help
```

Or install the console script (editable):

```bash
pip install -e .
workloadiq --help
```

## Quickstart

See the full loop instantly on a built-in scenario:

```bash
python3 -m workloadiq demo --scenario bigquery_bottleneck
```

Or run the file-based flow (matches the design doc CLI):

```bash
# 1. generate synthetic telemetry + a pipeline topology
python3 -m workloadiq generate \
  --scenario bigquery_bottleneck \
  --out examples/telemetry.csv \
  --pipeline-out examples/pipeline_a.json

# 2. analyze it
python3 -m workloadiq analyze \
  --input examples/telemetry.csv \
  --pipeline-config examples/pipeline_a.json \
  --format text
```

Example output:

```
Pipeline: pipeline_a
Symptom:  End-to-end latency increased

Likely Root Cause: BigQuery write bottleneck
Confidence: 0.88   Severity: high

Evidence:
  - bigquery write latency increased 6.4x
  - Worker CPU usage stayed stable (compute is not the bottleneck)
  - Pub/Sub backlog stayed within normal range
  - Job duration increased in step with sink latency

Recommended Actions:
  - Check BigQuery quota, slot reservations, and job concurrency
  - Inspect recent schema or partition/clustering changes
  ...

Forecast / Risk:
  - bigquery write_latency_ms is growing ~241% per hour ...
```

### Scenarios

```bash
python3 -m workloadiq scenarios
python3 -m workloadiq demo --scenario all      # run every scenario
```

| Scenario | Detects |
| --- | --- |
| `bigquery_bottleneck` | Downstream sink (BigQuery write) bottleneck |
| `compute_bottleneck` | CPU/memory saturation on workers |
| `queue_bottleneck` | Pub/Sub backlog growth |
| `retry_storm` | Failure + retry amplification |
| `over_provisioning` | Resource inefficiency (request ≫ usage) |
| `healthy` | No significant degradation |

## How it works

```
Telemetry (CSV/JSON)
   → Feature Builder     baseline vs recent window, p95, trend slope
   → Detector            significant up/down signals + symptom selection
   → RCA Engine          weighted, transparent rule scoring per candidate cause
   → Forecaster          linear trend → time-to-threshold risk lines
   → Recommendation      cause-specific next actions
   → Report              text / markdown / json
```

The RCA engine is deliberately rule-based (no ML in v0): every conclusion is
explainable through its evidence list and the ranked candidate scores.

## Telemetry format

One normalized row per sample (`workloadiq/data/loader.py`):

```
timestamp,pipeline_id,component_type,component_name,metric_name,metric_value,unit,labels
```

`component_type` is one of `queue | worker | sink`. Bring your own data by
emitting this schema — the synthetic generator is just one producer.

## Development

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest
```

## Layout

```
workloadiq/
  models.py        core data model (Pipeline, MetricRecord, RCAResult)
  stats.py         numeric helpers (quantile, linreg)
  data/
    generator.py   synthetic telemetry per scenario
    loader.py      CSV/JSON + pipeline config IO
  features.py      feature builder
  detect.py        anomaly/trend detector + symptom selection
  rca.py           rule-based RCA scoring engine
  forecast.py      linear-trend risk forecasting
  recommend.py     cause → recommendations
  report.py        text/markdown/json rendering
  engine.py        end-to-end orchestration
  cli.py           argparse CLI
tests/
```

## License

MIT
