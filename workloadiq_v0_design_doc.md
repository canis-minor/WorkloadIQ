# WorkloadIQ v0 Design Doc

## 1. Project Summary

**WorkloadIQ** is a lightweight forecasting and root cause analysis engine for event-driven GCP workloads.

The v0 scope focuses on a common production pipeline pattern:

```text
Pub/Sub → CPU Workers / Jobs → BigQuery / Bigtable / Elasticsearch
```

The goal is not to build another monitoring dashboard. The goal is to generate actionable intelligence from existing telemetry:

- Why did latency increase?
- Why did failures increase?
- Why did cost or resource usage increase?
- Which component is most likely the bottleneck?
- What is likely to happen next if the trend continues?

The first version is designed for CPU-based workloads, with a clear path to support GPU and LLM/agent workloads later.

---

## 2. Motivation

Many production systems already have metrics, logs, alerts, and dashboards. However, engineers still spend significant time manually correlating signals across queue systems, compute jobs, and downstream databases.

For example, when a pipeline becomes slow, the cause may come from multiple places:

- Pub/Sub backlog increased
- Workers are under-provisioned
- Jobs are retrying too often
- BigQuery write latency increased
- Bigtable mutations are throttled
- Elasticsearch indexing became slow
- A new deployment changed workload behavior

Existing observability systems can show these signals, but they often do not explain the causal chain.

WorkloadIQ aims to provide a focused RCA layer for event-driven workloads.

---

## 3. v0 Scope

### In Scope

v0 supports GCP-based event-driven pipelines with the following components:

```text
Pub/Sub
↓
CPU Worker / Kubernetes Job / Cloud Run Job
↓
BigQuery / Bigtable / Elasticsearch
```

The v0 system focuses on three insight types:

1. **Capacity Risk**  
   Detect whether backlog, latency, or resource usage is trending toward unsafe levels.

2. **Bottleneck Attribution**  
   Identify whether the issue is most likely caused by queue pressure, compute saturation, retries, or downstream sink latency.

3. **Resource Inefficiency**  
   Detect over-provisioned or under-provisioned jobs based on requested vs. actual CPU/memory usage.

### Out of Scope for v0

The following are intentionally excluded from v0:

- Full observability dashboard
- Generic APM replacement
- Agent framework
- LLM evaluation system
- GPU-specific optimization
- Automatic remediation
- Multi-cloud support
- Complex causal discovery models

These may be added later after the core RCA loop is validated.

---

## 4. Target Users

The initial users are infrastructure, ML platform, data platform, and AIOps engineers who operate event-driven compute pipelines.

Typical users want answers such as:

- Why did this batch pipeline slow down?
- Why is the Pub/Sub backlog growing?
- Which job is consuming the most CPU?
- Which job is over-provisioned?
- Is the bottleneck in compute or downstream storage?
- Will this pipeline hit capacity limits soon?

---

## 5. Example Use Case

### Scenario

A Pub/Sub-triggered pipeline starts experiencing high end-to-end latency.

Observed symptoms:

```text
End-to-end latency: 2 minutes → 15 minutes
Pub/Sub backlog: normal
Worker CPU usage: stable
Job duration: increased
BigQuery write latency: increased 8x
Retry count: slightly increased
```

### WorkloadIQ Output

```json
{
  "root_cause": "BigQuery write bottleneck",
  "confidence": 0.84,
  "impact": "End-to-end latency increased by approximately 13 minutes",
  "evidence": [
    "Pub/Sub backlog remained within normal range",
    "Worker CPU utilization remained stable",
    "Job duration increased during the same time window",
    "BigQuery write latency increased 8x",
    "Retry count increased after BigQuery latency increased"
  ],
  "recommendations": [
    "Check BigQuery quota and job concurrency",
    "Inspect recent schema or partition changes",
    "Review write batch size and retry behavior",
    "Add temporary throttling or buffering if backlog begins to grow"
  ]
}
```

---

## 6. Data Sources

### Queue Metrics

From Pub/Sub:

- Publish rate
- Ack rate
- Backlog size
- Oldest unacked message age
- Ack latency
- Redelivery count
- Dead letter count

### Compute Metrics

From Kubernetes, Cloud Run, or job metadata:

- CPU request
- CPU usage
- Memory request
- Memory usage
- Job duration
- Job status
- Failure rate
- Retry count
- Pod restart count
- Queue time
- Worker concurrency

### Sink Metrics

From BigQuery, Bigtable, Elasticsearch, or other storage systems:

- Write latency
- Read latency
- Error rate
- Throttling rate
- Mutation latency
- Indexing latency
- Query latency
- Cost-related metrics if available

### Optional Metadata

- Deployment version
- Job name
- Namespace
- Team
- Service owner
- Pipeline name
- Region
- Cluster name

---

## 7. Core Data Model

### Pipeline Entity

```yaml
pipeline_id: string
pipeline_name: string
queue: string
workers:
  - worker_name: string
    worker_type: cpu
sinks:
  - sink_name: string
    sink_type: bigquery | bigtable | elasticsearch
owner: string
region: string
```

### Time-Series Metric Record

```yaml
timestamp: datetime
pipeline_id: string
component_type: queue | worker | sink
component_name: string
metric_name: string
metric_value: float
unit: string
labels: map
```

### RCA Result

```yaml
incident_id: string
pipeline_id: string
start_time: datetime
end_time: datetime
symptom: string
root_cause: string
confidence: float
evidence:
  - string
recommendations:
  - string
severity: low | medium | high
```

---

## 8. System Architecture

```text
GCP Metrics / Logs / Job Metadata
        ↓
Telemetry Collector
        ↓
Feature Builder
        ↓
Anomaly + Trend Detector
        ↓
RCA Engine
        ↓
Recommendation Generator
        ↓
CLI / Markdown Report / Dashboard
```

### Component Responsibilities

#### Telemetry Collector

Collects or loads metrics from GCP services and normalizes them into a common schema.

#### Feature Builder

Computes derived features such as:

- Rolling averages
- p95 latency
- Change rate
- Retry ratio
- Request-to-usage ratio
- Backlog growth rate
- Sink latency change

#### Anomaly + Trend Detector

Detects unusual changes in key metrics:

- Sudden spikes
- Sustained increases
- Deviation from baseline
- Forecasted capacity risk

#### RCA Engine

Ranks likely root causes based on temporal correlation, dependency graph, and rule-based evidence.

#### Recommendation Generator

Produces human-readable recommendations based on the detected root cause.

---

## 9. RCA Logic v0

v0 uses a rule-based and evidence-scoring approach rather than complex machine learning.

### Example Rules

#### Queue Bottleneck

Likely if:

- Pub/Sub backlog increases
- Oldest unacked message age increases
- Worker throughput does not increase
- Sink latency remains normal

#### Compute Bottleneck

Likely if:

- Job duration increases
- CPU usage is high
- Memory usage is high or OOM events appear
- Backlog increases after compute saturation

#### Retry Storm

Likely if:

- Failure rate increases
- Retry count increases
- CPU usage and cost increase
- Successful output does not increase proportionally

#### Downstream Sink Bottleneck

Likely if:

- Job duration increases
- CPU usage remains normal
- Queue backlog may or may not increase
- BigQuery / Bigtable / Elasticsearch latency increases first

#### Over-Provisioning

Likely if:

- CPU request is much higher than p95 CPU usage
- Memory request is much higher than p95 memory usage
- Job success rate is stable
- Latency is not improved by high resource request

---

## 10. Forecasting v0

The v0 forecasting layer should stay simple.

Supported forecasts:

- Backlog growth forecast
- CPU usage trend
- Job duration trend
- Sink latency trend

Initial methods:

- Rolling average
- Linear trend
- Quantile-based thresholding
- Simple time-window comparison

The goal is not to provide perfect long-term forecasting. The goal is to detect whether the system is trending toward operational risk.

Example output:

```text
Pub/Sub backlog is growing at 12% per hour. At the current rate, the safe threshold may be exceeded in 6 hours.
```

---

## 11. Recommendation Examples

### BigQuery Bottleneck

```text
Check BigQuery quota, partition design, write batch size, and recent schema changes.
```

### Bigtable Bottleneck

```text
Check hotspotting, mutation latency, row key distribution, and instance node utilization.
```

### Elasticsearch Bottleneck

```text
Check indexing latency, shard health, refresh interval, bulk request size, and rejected writes.
```

### Compute Bottleneck

```text
Increase worker concurrency, tune CPU/memory requests, or inspect recent code changes that increased job duration.
```

### Retry Storm

```text
Inspect recent error types, retry policy, dead letter queue behavior, and whether failures are deterministic.
```

### Over-Provisioning

```text
Reduce CPU or memory request for jobs with consistently low p95 usage relative to requested resources.
```

---

## 12. MVP Interface

### CLI Example

```bash
workloadiq analyze \
  --pipeline pipeline_a \
  --start 2026-06-01T00:00:00Z \
  --end 2026-06-01T06:00:00Z
```

### Output Example

```text
Pipeline: pipeline_a
Symptom: End-to-end latency increased
Likely Root Cause: BigQuery write bottleneck
Confidence: 0.84

Evidence:
- BigQuery write latency increased 8x
- Worker CPU usage stayed stable
- Pub/Sub backlog stayed normal
- Job duration increased after BigQuery latency increased

Recommended Actions:
- Check BigQuery quota and write concurrency
- Inspect recent schema or partition changes
- Review retry behavior and batch size
```

---

## 13. Success Criteria

v0 is successful if it can do the following on sample or real telemetry:

1. Detect that a pipeline has degraded.
2. Identify the most likely bottleneck among queue, compute, retry, or sink.
3. Provide clear evidence for the conclusion.
4. Generate a useful recommendation.
5. Produce an output that an engineer would find faster than manually checking multiple dashboards.

---

## 14. Future Extensions

### v1: More GCP Sources

- Cloud Run metrics
- GKE metrics
- Bigtable metrics
- BigQuery job metadata
- Cloud Logging integration

### v2: LLM / Agent Workloads

Add agent-level telemetry:

- Agent name
- Tool call latency
- Model name
- Prompt version
- Input tokens
- Output tokens
- Cost
- Retry count
- Error type

### v3: GPU Workloads

Add GPU-specific metrics:

- GPU utilization
- GPU memory utilization
- Model name
- Batch size
- Tokens per second
- Inference latency
- Training job duration

### v4: Learning-Based RCA

Move beyond rules by using:

- Historical incident memory
- Similar incident retrieval
- Causal graph scoring
- Supervised labels from past RCA tickets
- Human feedback on RCA quality

---

## 15. Positioning

WorkloadIQ is not intended to replace Datadog, Grafana, Cloud Monitoring, Langfuse, or FinOps tools.

Instead, it sits above them as an intelligence layer:

```text
Monitoring tells you what changed.
WorkloadIQ explains why it changed and what to do next.
```

The narrow v0 positioning is:

> Forecasting and root cause analysis for event-driven GCP workloads.

The long-term positioning is:

> AI workload intelligence for CPU, GPU, and agentic pipelines.
