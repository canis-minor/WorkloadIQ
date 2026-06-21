"""Render an ``RCAResult`` as text, markdown, or JSON (design doc section 12)."""

from __future__ import annotations

import json

from .models import RCAResult

_SEV_ICON = {"low": "·", "medium": "▲", "high": "■"}


def to_json(result: RCAResult) -> str:
    return json.dumps(result.to_dict(), indent=2)


def to_text(result: RCAResult) -> str:
    lines = [
        f"Pipeline: {result.pipeline_id}",
        f"Window:   {result.start_time.isoformat()} -> {result.end_time.isoformat()}",
        f"Symptom:  {result.symptom}",
        "",
        f"Likely Root Cause: {result.root_cause}",
        f"Confidence: {result.confidence:.2f}   Severity: {result.severity.value}",
        "",
        "Evidence:",
    ]
    lines += [f"  - {e}" for e in result.evidence]
    if result.recommendations:
        lines += ["", "Recommended Actions:"]
        lines += [f"  - {r}" for r in result.recommendations]
    if result.forecasts:
        lines += ["", "Forecast / Risk:"]
        lines += [f"  - {f}" for f in result.forecasts]
    if result.ranked_causes:
        lines += ["", "Ranked candidates:"]
        for cause, score in result.ranked_causes:
            lines.append(f"  {score:0.2f}  {cause}")
    return "\n".join(lines)


def to_markdown(result: RCAResult) -> str:
    icon = _SEV_ICON.get(result.severity.value, "")
    out = [
        f"# RCA Report — {result.pipeline_id}",
        "",
        f"- **Window:** {result.start_time.isoformat()} → {result.end_time.isoformat()}",
        f"- **Symptom:** {result.symptom}",
        f"- **Root cause:** {result.root_cause}",
        f"- **Confidence:** {result.confidence:.2f}",
        f"- **Severity:** {icon} {result.severity.value}",
        "",
        "## Evidence",
    ]
    out += [f"- {e}" for e in result.evidence]
    if result.recommendations:
        out += ["", "## Recommended actions"]
        out += [f"- {r}" for r in result.recommendations]
    if result.forecasts:
        out += ["", "## Forecast / risk"]
        out += [f"- {f}" for f in result.forecasts]
    if result.ranked_causes:
        out += ["", "## Ranked candidates", "", "| Score | Candidate |", "| --- | --- |"]
        out += [f"| {score:.2f} | {cause} |" for cause, score in result.ranked_causes]
    return "\n".join(out)


def render(result: RCAResult, fmt: str = "text") -> str:
    fmt = fmt.lower()
    if fmt == "json":
        return to_json(result)
    if fmt in ("md", "markdown"):
        return to_markdown(result)
    return to_text(result)
