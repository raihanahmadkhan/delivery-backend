import argparse
import json
from pathlib import Path

from .experiments import run_experiment, run_once
from .importers import import_file
from .models import ExperimentRequest, RunOptions
from .presets import CATALOG, get_scenario


def main():
    parser = argparse.ArgumentParser(description="RouteLab: reproducible local routing experiments")
    parser.add_argument("--preset", choices=[p["id"] for p in CATALOG], default="harbor")
    parser.add_argument("--input", type=Path, help="RouteLab JSON, CSV, or Solomon text")
    parser.add_argument(
        "--algorithm",
        default="alns",
        choices=["greedy", "local_search", "alns", "exact", "ortools"],
    )
    parser.add_argument("--seconds", type=float, default=3)
    parser.add_argument("--iterations", type=int, default=600)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--experiment", action="store_true")
    parser.add_argument("--seeds", default="11,22,33")
    parser.add_argument("--algorithms", default="greedy,local_search,alns")
    parser.add_argument("--no-adaptive", action="store_true")
    parser.add_argument("--no-local-search", action="store_true")
    parser.add_argument(
        "--road", action="store_true", help="Freeze a table from operator-configured local OSRM"
    )
    parser.add_argument("--output", type=Path, help="Retain the complete JSON artifact")
    args = parser.parse_args()
    scenario = (
        import_file(args.input.name, args.input.read_bytes())
        if args.input
        else get_scenario(args.preset)
    )
    if args.road:
        from . import road, store

        store.initialize()
        scenario = road.snapshot(scenario)
    if args.experiment:
        result = run_experiment(
            ExperimentRequest(
                scenario=scenario,
                algorithms=args.algorithms.split(","),
                seeds=[int(x) for x in args.seeds.split(",")],
                time_limit_seconds=args.seconds,
                iterations=args.iterations,
                adaptive=not args.no_adaptive,
                local_improvement=not args.no_local_search,
            )
        )
        summary = result["summary"]
    else:
        result = run_once(
            scenario,
            RunOptions(
                algorithm=args.algorithm,
                seed=args.seed,
                time_limit_seconds=args.seconds,
                iterations=args.iterations,
                adaptive=not args.no_adaptive,
                local_improvement=not args.no_local_search,
            ),
        )
        summary = {
            key: result[key]
            for key in ("status", "termination_reason", "solver_time_ms", "evaluations")
        }
        summary["objective"] = result["evaluation"]["objective"]
        summary["violations"] = result["evaluation"]["violations"]
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
