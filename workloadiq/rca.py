"""Rule-based RCA engine (design doc section 9).

Each candidate cause is scored in [0,1] by accumulating weighted evidence from
the feature set. The winner becomes the root cause; confidence reflects both the
winner's strength and its margin over the runner-up. This is deliberately
transparent (no ML) so every conclusion is explainable via its evidence list.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .features import FeatureSet, get
from .models import Pipeline, Severity, SinkType

# --- tuning constants ---------------------------------------------------------
INCIDENT_FLOOR = 0.35   # below this, no incident is asserted
EFFICIENCY_FLOOR = 0.65  # over-provisioning must be this strong to report
MAX_CONFIDENCE = 0.95

_SINK_DISPLAY = {
    SinkType.BIGQUERY: "BigQuery",
    SinkType.BIGTABLE: "Bigtable",
    SinkType.ELASTICSEARCH: "Elasticsearch",
}


# --- strength helpers ---------------------------------------------------------
def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def up_strength(cr: float, target: float) -> float:
    """1.0 when change ratio reaches ``target``x, scaling down to 0 at 1x."""
    if cr == float("inf"):
        return 1.0
    if cr <= 1.0 or target <= 1.0:
        return 0.0
    return _clamp((cr - 1.0) / (target - 1.0))


def stable_strength(cr: float, tol: float = 0.3) -> float:
    """1.0 when the metric barely moved; 0 once it deviates by ``tol``."""
    if cr == float("inf"):
        return 0.0
    return _clamp(1.0 - abs(cr - 1.0) / tol)


def not_increasing_strength(cr: float, slack: float = 0.5) -> float:
    """1.0 when flat/declining; decays as it rises past ~5%."""
    if cr == float("inf"):
        return 0.0
    if cr <= 1.05:
        return 1.0
    return _clamp(1.0 - (cr - 1.05) / slack)


@dataclass
class CauseScore:
    label: str
    score: float
    evidence: list[str] = field(default_factory=list)
    incident: bool = True


class RCAEngine:
    def __init__(self, features: dict[tuple[str, str], FeatureSet], pipeline: Pipeline | None = None):
        self.f = features
        self.pipeline = pipeline

    # convenience accessors -----------------------------------------------------
    def _cr(self, metric: str, component: str | None = None) -> float:
        fs = get(self.f, metric, component)
        return fs.change_ratio if fs else 1.0

    def _fs(self, metric: str, component: str | None = None) -> FeatureSet | None:
        return get(self.f, metric, component)

    def _max_sink_latency(self) -> tuple[FeatureSet | None, str]:
        """Return the sink-latency feature with the largest change, and its kind."""
        best: FeatureSet | None = None
        best_kind = "write"
        for (comp, metric), fs in self.f.items():
            if fs.component_type != "sink":
                continue
            if metric not in ("write_latency_ms", "query_latency_ms", "read_latency_ms"):
                continue
            if best is None or fs.change_ratio > best.change_ratio:
                best = fs
                best_kind = "query" if metric.startswith("query") else (
                    "read" if metric.startswith("read") else "write"
                )
        return best, best_kind

    def _sink_label(self, fs: FeatureSet | None, kind: str) -> str:
        name = fs.component_name if fs else "downstream sink"
        sink_type = None
        if self.pipeline:
            for s in self.pipeline.sinks:
                if s.sink_name == name:
                    sink_type = s.sink_type
        display = _SINK_DISPLAY.get(sink_type, name.capitalize()) if sink_type else name.capitalize()
        return f"{display} {kind} bottleneck"

    # individual rules ----------------------------------------------------------
    def _rule_queue(self) -> CauseScore:
        ev: list[str] = []
        score = 0.0
        backlog = self._fs("backlog_size")
        if backlog:
            s = up_strength(backlog.change_ratio, 3.0)
            score += 0.45 * s
            if s > 0.3:
                ev.append(f"Pub/Sub backlog rose {backlog.change_ratio:.1f}x "
                          f"({backlog.baseline_mean:.0f} -> {backlog.recent_mean:.0f} msg)")
        age = self._fs("oldest_unacked_age_s")
        if age:
            s = up_strength(age.change_ratio, 3.0)
            score += 0.25 * s
            if s > 0.3:
                ev.append(f"Oldest unacked message age rose {age.change_ratio:.1f}x")
        thr = self._cr("throughput")
        s = not_increasing_strength(thr)
        score += 0.15 * s
        if s > 0.5 and backlog and up_strength(backlog.change_ratio, 3.0) > 0.3:
            ev.append("Worker throughput did not increase to drain the backlog")
        sink_fs, _ = self._max_sink_latency()
        sink_cr = sink_fs.change_ratio if sink_fs else 1.0
        s = stable_strength(sink_cr)
        score += 0.15 * s
        if s > 0.5 and score > 0.3:
            ev.append("Downstream sink latency stayed within normal range")
        return CauseScore("Queue backlog bottleneck", _clamp(score), ev)

    def _rule_compute(self) -> CauseScore:
        ev: list[str] = []
        score = 0.0
        dur = self._fs("job_duration_s")
        if dur:
            s = up_strength(dur.change_ratio, 2.0)
            score += 0.30 * s
            if s > 0.3:
                ev.append(f"Job duration increased {dur.change_ratio:.1f}x")
        cpu_use = self._fs("cpu_usage")
        cpu_req = self._fs("cpu_request")
        if cpu_use and cpu_req and cpu_req.recent_mean > 0:
            util = cpu_use.recent_p95 / cpu_req.recent_mean
            s = _clamp((util - 0.6) / 0.35)
            score += 0.35 * s
            if s > 0.3:
                ev.append(f"CPU utilization reached {util*100:.0f}% of request (saturation)")
        mem_use = self._fs("mem_usage")
        mem_req = self._fs("mem_request")
        restarts = self._cr("pod_restart_count")
        mem_s = 0.0
        if mem_use and mem_req and mem_req.recent_mean > 0:
            mem_util = mem_use.recent_p95 / mem_req.recent_mean
            mem_s = max(mem_s, _clamp((mem_util - 0.7) / 0.25))
        if restarts != float("inf") and restarts >= 1.5:
            mem_s = max(mem_s, 0.7)
        score += 0.15 * mem_s
        if mem_s > 0.3:
            ev.append("Memory pressure / pod restarts observed during the window")
        backlog_cr = self._cr("backlog_size")
        s = up_strength(backlog_cr, 3.0)
        score += 0.20 * s
        if s > 0.3 and dur and up_strength(dur.change_ratio, 2.0) > 0.3:
            ev.append("Backlog grew after compute saturation")
        return CauseScore("Compute saturation bottleneck", _clamp(score), ev)

    def _rule_retry(self) -> CauseScore:
        ev: list[str] = []
        score = 0.0
        fail = self._fs("failure_rate")
        if fail:
            s = up_strength(fail.change_ratio, 5.0)
            score += 0.30 * s
            if s > 0.3:
                ev.append(f"Failure rate increased {fail.change_ratio:.1f}x "
                          f"({fail.baseline_mean:.3f} -> {fail.recent_mean:.3f})")
        retry = self._fs("retry_count")
        if retry:
            s = up_strength(retry.change_ratio, 4.0)
            score += 0.30 * s
            if s > 0.3:
                ev.append(f"Retry count increased {retry.change_ratio:.1f}x")
        cpu = self._cr("cpu_usage")
        s = up_strength(cpu, 1.8)
        score += 0.20 * s
        if s > 0.3:
            ev.append("CPU usage rose alongside retries (wasted work)")
        thr = self._cr("throughput")
        s = not_increasing_strength(thr)
        if (fail and up_strength(fail.change_ratio, 5.0) > 0.3):
            score += 0.20 * s
            if s > 0.5:
                ev.append("Successful throughput did not rise proportionally to the extra work")
        return CauseScore("Retry storm", _clamp(score), ev)

    def _rule_sink(self) -> CauseScore:
        ev: list[str] = []
        score = 0.0
        sink_fs, kind = self._max_sink_latency()
        if sink_fs:
            s = up_strength(sink_fs.change_ratio, 4.0)
            score += 0.50 * s
            if s > 0.3:
                ev.append(f"{sink_fs.component_name} {kind} latency increased "
                          f"{sink_fs.change_ratio:.1f}x")
        dur = self._fs("job_duration_s")
        if dur:
            s = up_strength(dur.change_ratio, 3.0)
            score += 0.25 * s
            if s > 0.3:
                ev.append("Job duration increased in step with sink latency")
        cpu = self._cr("cpu_usage")
        s = stable_strength(cpu, tol=0.4)
        score += 0.15 * s
        if s > 0.5 and sink_fs and up_strength(sink_fs.change_ratio, 4.0) > 0.3:
            ev.append("Worker CPU usage stayed stable (compute is not the bottleneck)")
        backlog_cr = self._cr("backlog_size")
        s = stable_strength(backlog_cr, tol=0.5)
        score += 0.10 * s
        if s > 0.5 and sink_fs and up_strength(sink_fs.change_ratio, 4.0) > 0.3:
            ev.append("Pub/Sub backlog stayed within normal range")
        label = self._sink_label(sink_fs, kind)
        return CauseScore(label, _clamp(score), ev)

    def _rule_over_provision(self) -> CauseScore:
        ev: list[str] = []
        score = 0.0
        cpu_use = self._fs("cpu_usage")
        cpu_req = self._fs("cpu_request")
        if cpu_use and cpu_req and cpu_use.recent_p95 > 0:
            ratio = cpu_req.recent_mean / cpu_use.recent_p95
            s = up_strength(ratio, 4.0)
            score += 0.50 * s
            if s > 0.3:
                ev.append(f"CPU request is {ratio:.1f}x the p95 CPU usage "
                          f"({cpu_req.recent_mean:.1f} vs {cpu_use.recent_p95:.1f} cores)")
        mem_use = self._fs("mem_usage")
        mem_req = self._fs("mem_request")
        if mem_use and mem_req and mem_use.recent_p95 > 0:
            ratio = mem_req.recent_mean / mem_use.recent_p95
            s = up_strength(ratio, 4.0)
            score += 0.30 * s
            if s > 0.3:
                ev.append(f"Memory request is {ratio:.1f}x the p95 memory usage")
        fail = self._cr("failure_rate")
        s = stable_strength(fail, tol=0.5)
        score += 0.10 * s
        dur = self._cr("job_duration_s")
        s = stable_strength(dur, tol=0.3)
        score += 0.10 * s
        if score > EFFICIENCY_FLOOR:
            ev.append("Success rate and latency are stable despite high resource requests")
        return CauseScore("Resource over-provisioning", _clamp(score), ev, incident=False)

    # orchestration -------------------------------------------------------------
    def score_all(self) -> list[CauseScore]:
        return [
            self._rule_sink(),
            self._rule_compute(),
            self._rule_retry(),
            self._rule_queue(),
            self._rule_over_provision(),
        ]

    def rank(self) -> dict:
        scores = self.score_all()
        incident = sorted([c for c in scores if c.incident], key=lambda c: c.score, reverse=True)
        efficiency = [c for c in scores if not c.incident]
        best_incident = incident[0] if incident else None
        best_eff = max(efficiency, key=lambda c: c.score) if efficiency else None

        ranked = sorted(scores, key=lambda c: c.score, reverse=True)
        ranked_pairs = [(c.label, c.score) for c in ranked]

        if best_incident and best_incident.score >= INCIDENT_FLOOR:
            s0 = best_incident.score
            s1 = incident[1].score if len(incident) > 1 else 0.0
            margin = (s0 - s1) / s0 if s0 > 0 else 0.0
            confidence = _clamp(s0 * (0.6 + 0.4 * margin), 0.0, MAX_CONFIDENCE)
            return {
                "root_cause": best_incident.label,
                "confidence": confidence,
                "evidence": best_incident.evidence,
                "ranked": ranked_pairs,
                "is_incident": True,
                "cause_obj": best_incident,
            }

        if best_eff and best_eff.score >= EFFICIENCY_FLOOR:
            return {
                "root_cause": best_eff.label,
                "confidence": _clamp(best_eff.score * 0.9, 0.0, MAX_CONFIDENCE),
                "evidence": best_eff.evidence,
                "ranked": ranked_pairs,
                "is_incident": False,
                "cause_obj": best_eff,
            }

        return {
            "root_cause": "No significant degradation detected",
            "confidence": _clamp(0.5 - (best_incident.score if best_incident else 0.0)),
            "evidence": ["All key metrics remained within normal range relative to baseline"],
            "ranked": ranked_pairs,
            "is_incident": False,
            "cause_obj": None,
        }


def severity_from_signals(signals, is_incident: bool) -> Severity:
    if not is_incident:
        return Severity.LOW
    from .detect import INCREASE_IS_BAD
    worst = 1.0
    for s in signals:
        if s.direction == "up" and s.metric_name in INCREASE_IS_BAD:
            cr = s.change_ratio if s.change_ratio != float("inf") else 100.0
            worst = max(worst, cr)
    if worst >= 4.0:
        return Severity.HIGH
    if worst >= 2.0:
        return Severity.MEDIUM
    return Severity.LOW
