"""WorkloadIQ command-line interface (design doc section 12).

Subcommands:
  generate   write synthetic telemetry for a scenario to CSV
  analyze    run the RCA loop over a telemetry file
  demo       generate + analyze in memory and print the report
  scenarios  list available synthetic scenarios
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .data import generator, loader
from .engine import analyze_pipeline
from .models import ComponentType, Pipeline, Sink, SinkType, Worker
from .report import render


def _parse_ts(raw: str | None) -> datetime | None:
    if not raw:
        return None
    dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _infer_pipeline(records) -> Pipeline:
    """Build a minimal topology from telemetry when no config file is supplied."""
    pid = records[0].pipeline_id
    workers, sinks, seen = [], [], set()
    queue = "pubsub"
    for r in records:
        if r.component_name in seen:
            continue
        seen.add(r.component_name)
        if r.component_type == ComponentType.WORKER:
            workers.append(Worker(r.component_name))
        elif r.component_type == ComponentType.SINK:
            try:
                stype = SinkType(r.component_name.lower())
            except ValueError:
                stype = SinkType.BIGQUERY
            sinks.append(Sink(r.component_name, stype))
        elif r.component_type == ComponentType.QUEUE:
            queue = r.component_name
    return Pipeline(pipeline_id=pid, pipeline_name=pid, queue=queue, workers=workers, sinks=sinks)


def _filter_window(records, start, end):
    if start:
        records = [r for r in records if r.timestamp >= start]
    if end:
        records = [r for r in records if r.timestamp <= end]
    return records


# --- subcommand handlers ------------------------------------------------------
def cmd_generate(args) -> int:
    end = _parse_ts(args.end)
    pipeline, records = generator.generate(
        scenario=args.scenario,
        pipeline_id=args.pipeline,
        hours=args.hours,
        step_seconds=args.step,
        end=end,
        seed=args.seed,
    )
    loader.write_csv(records, args.out)
    print(f"Wrote {len(records)} records ({args.scenario}) to {args.out}")
    if args.pipeline_out:
        loader.write_pipeline(pipeline, args.pipeline_out)
        print(f"Wrote pipeline config to {args.pipeline_out}")
    return 0


def cmd_analyze(args) -> int:
    records = loader.read_telemetry(args.input)
    records = _filter_window(records, _parse_ts(args.start), _parse_ts(args.end))
    if not records:
        print("No telemetry records in the selected window.", file=sys.stderr)
        return 1
    pipeline = loader.read_pipeline(args.pipeline_config) if args.pipeline_config else _infer_pipeline(records)
    result = analyze_pipeline(pipeline, records, baseline_frac=args.baseline_frac, recent_frac=args.recent_frac)
    output = render(result, args.format)
    if args.out:
        Path(args.out).write_text(output)
        print(f"Wrote report to {args.out}")
    else:
        print(output)
    return 0


def cmd_demo(args) -> int:
    scenarios = generator.SCENARIOS if args.scenario == "all" else [args.scenario]
    for i, scenario in enumerate(scenarios):
        pipeline, records = generator.generate(scenario=scenario, pipeline_id=args.pipeline, hours=args.hours)
        result = analyze_pipeline(pipeline, records)
        if len(scenarios) > 1:
            print("=" * 72)
            print(f"SCENARIO: {scenario}")
            print("=" * 72)
        print(render(result, args.format))
        if i != len(scenarios) - 1:
            print()
    return 0


def cmd_scenarios(args) -> int:
    print("Available synthetic scenarios:")
    for s in generator.SCENARIOS:
        print(f"  - {s}")
    return 0


# --- parser -------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="workloadiq", description=__doc__.splitlines()[0])
    p.add_argument("--version", action="version", version=f"workloadiq {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    g = sub.add_parser("generate", help="write synthetic telemetry to CSV")
    g.add_argument("--scenario", default="bigquery_bottleneck", choices=generator.SCENARIOS)
    g.add_argument("--pipeline", default="pipeline_a")
    g.add_argument("--hours", type=float, default=3.0)
    g.add_argument("--step", type=int, default=60, help="sample interval in seconds")
    g.add_argument("--end", default=None, help="ISO end timestamp (default: now)")
    g.add_argument("--seed", type=int, default=7)
    g.add_argument("--out", default="examples/telemetry.csv")
    g.add_argument("--pipeline-out", default=None, help="also write pipeline config JSON")
    g.set_defaults(func=cmd_generate)

    a = sub.add_parser("analyze", help="run RCA over a telemetry file")
    a.add_argument("--input", required=True, help="telemetry CSV or JSON")
    a.add_argument("--pipeline-config", default=None, help="pipeline topology JSON (optional)")
    a.add_argument("--start", default=None, help="ISO start of analysis window")
    a.add_argument("--end", default=None, help="ISO end of analysis window")
    a.add_argument("--format", default="text", choices=["text", "json", "md", "markdown"])
    a.add_argument("--baseline-frac", type=float, default=0.5)
    a.add_argument("--recent-frac", type=float, default=0.25)
    a.add_argument("--out", default=None, help="write report to file instead of stdout")
    a.set_defaults(func=cmd_analyze)

    d = sub.add_parser("demo", help="generate + analyze in memory and print the report")
    d.add_argument("--scenario", default="bigquery_bottleneck", choices=generator.SCENARIOS + ["all"])
    d.add_argument("--pipeline", default="pipeline_a")
    d.add_argument("--hours", type=float, default=3.0)
    d.add_argument("--format", default="text", choices=["text", "json", "md", "markdown"])
    d.set_defaults(func=cmd_demo)

    s = sub.add_parser("scenarios", help="list available synthetic scenarios")
    s.set_defaults(func=cmd_scenarios)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
