"""Multi-instance benchmark and ablation runner. Run on an idle machine."""

import argparse
import csv
import json
import time
from pathlib import Path

from . import VERSION
from .experiments import environment, run_experiment
from .models import ExperimentRequest
from .presets import CATALOG, get_scenario


def write_json(path, body):
    with path.open("x", encoding="utf-8") as handle:
        json.dump(body, handle, indent=2, allow_nan=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="New or empty artifact directory; never overwrites evidence",
    )
    parser.add_argument("--presets", default="tiny,harbor,tight,scattered")
    parser.add_argument("--seeds", default="11,22,33")
    parser.add_argument("--seconds", type=float, default=1)
    parser.add_argument("--iterations", type=int, default=400)
    parser.add_argument("--ablations", action="store_true")
    parser.add_argument(
        "--ortools", action="store_true", help="Include the optional installed reference"
    )
    args = parser.parse_args()
    names, seeds = args.presets.split(","), [int(seed) for seed in args.seeds.split(",")]
    if len(set(names)) != len(names) or any(
        name not in {p["id"] for p in CATALOG} for name in names
    ):
        parser.error("Preset IDs must be known and unique")
    if args.output.exists() and any(args.output.iterdir()):
        parser.error(
            "Output directory must be empty; existing benchmark evidence is never replaced"
        )
    cases = []
    for name in names:
        scenario = get_scenario(name)
        algorithms = (
            ["greedy", "local_search", "alns"]
            + (["exact"] if len(scenario.nodes) <= 9 else [])
            + (["ortools"] if args.ortools else [])
        )
        variants = [("full", algorithms, True, True)]
        if args.ablations:
            variants += [
                ("no-adaptation", ["alns"], False, True),
                ("no-local-search", ["alns"], True, False),
            ]
        for variant, methods, adaptive, local in variants:
            request = ExperimentRequest(
                scenario=scenario,
                algorithms=methods,
                seeds=seeds,
                time_limit_seconds=args.seconds,
                iterations=args.iterations,
                adaptive=adaptive,
                local_improvement=local,
            )
            cases.append((name, variant, request))
    args.output.mkdir(parents=True, exist_ok=True)
    manifest = {
        "version": VERSION,
        "environment": environment(),
        "created": time.time(),
        "status": "running",
        "cases": [
            {"preset": name, "variant": variant, "request": request.model_dump()}
            for name, variant, request in cases
        ],
        "artifacts": [],
    }
    write_json(args.output / "manifest-start.json", manifest)
    rows = []
    for name, variant, request in cases:
        print(f"{name} / {variant}: {len(request.algorithms) * len(seeds)} trials", flush=True)
        result = run_experiment(request)
        filename = f"{name}-{variant}.json"
        write_json(args.output / filename, result)
        manifest["artifacts"].append(filename)
        for trial in result["trials"]:
            ev = trial.get("evaluation", {})
            rows.append(
                [
                    name,
                    variant,
                    trial["algorithm"],
                    trial["options"]["seed"],
                    trial["status"],
                    ev.get("feasible"),
                    ev.get("vehicles_used"),
                    ev.get("distance_km"),
                    trial.get("solver_time_ms"),
                    trial.get("scenario_hash"),
                    trial.get("matrix_hash"),
                ]
            )
    with (args.output / "trials.csv").open("x", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "preset",
                "variant",
                "algorithm",
                "seed",
                "status",
                "feasible",
                "vehicles",
                "distance_km",
                "solver_ms",
                "scenario_hash",
                "matrix_hash",
            ]
        )
        writer.writerows(rows)
    manifest.update(status="completed", finished=time.time(), trials=len(rows))
    write_json(args.output / "manifest-complete.json", manifest)
    print(f"Retained {len(rows)} trials in {args.output.resolve()}")


if __name__ == "__main__":
    main()
