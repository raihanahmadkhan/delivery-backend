import contextlib
import hashlib
import importlib.metadata
import platform
import statistics
import time
from functools import lru_cache
from pathlib import Path

from . import VERSION
from .evaluator import evaluate
from .matrices import build_matrix, digest
from .models import RunOptions
from .solvers import solve


@lru_cache(maxsize=1)
def source_fingerprint():
    source = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob("*.py")):
        source.update(path.name.encode())
        source.update(path.read_bytes().replace(b"\r\n", b"\n"))
    return source.hexdigest()


def environment():
    packages = {}
    for name in ("pydantic", "ortools"):
        with contextlib.suppress(importlib.metadata.PackageNotFoundError):
            packages[name] = importlib.metadata.version(name)
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "processor": platform.processor(),
        "packages": packages,
        "source_sha256": source_fingerprint(),
    }


def run_once(scenario, options, progress=None, cancelled=None):
    started = time.perf_counter()
    matrix = build_matrix(scenario)
    preparation_ms = (time.perf_counter() - started) * 1000
    result = solve(scenario, matrix, options, progress, cancelled)
    validation_start = time.perf_counter()
    result["evaluation"] = evaluate(scenario, matrix, result["routes"])
    result["validation_time_ms"] = (time.perf_counter() - validation_start) * 1000
    result.update(
        {
            "scenario": scenario.model_dump(),
            "scenario_hash": digest(scenario.model_dump()),
            "matrix_hash": matrix.hash,
            "matrix_provenance": matrix.provenance,
            "options": options.model_dump(),
            "solver_version": VERSION,
            "environment": environment(),
            "preparation_time_ms": preparation_ms,
            "total_time_ms": (time.perf_counter() - started) * 1000,
        }
    )
    return result


def paired_comparisons(trials, algorithms, planned_seeds=None):
    baseline = algorithms[0]
    indexed = {(trial["algorithm"], trial["options"]["seed"]): trial for trial in trials}
    seeds = (
        planned_seeds
        if planned_seeds is not None
        else sorted({trial["options"]["seed"] for trial in trials})
    )
    comparisons = []
    for algorithm in algorithms[1:]:
        row = {
            "algorithm": algorithm,
            "baseline": baseline,
            "wins": 0,
            "ties": 0,
            "losses": 0,
            "both_infeasible": 0,
            "missing_or_error": 0,
        }
        for seed in seeds:
            candidate, reference = indexed.get((algorithm, seed)), indexed.get((baseline, seed))
            if (
                not candidate
                or not reference
                or "evaluation" not in candidate
                or "evaluation" not in reference
            ):
                row["missing_or_error"] += 1
                continue
            a, b = candidate["evaluation"], reference["evaluation"]
            if not a["feasible"] and not b["feasible"]:
                row["both_infeasible"] += 1
            elif a["feasible"] != b["feasible"]:
                row["wins" if a["feasible"] else "losses"] += 1
            elif a["vehicles_used"] != b["vehicles_used"]:
                row["wins" if a["vehicles_used"] < b["vehicles_used"] else "losses"] += 1
            else:
                difference = a["distance_km"] - b["distance_km"]
                row[
                    "ties" if abs(difference) <= 1e-7 else "wins" if difference < 0 else "losses"
                ] += 1
        comparisons.append(row)
    return comparisons


def annotate_exact_gaps(trials):
    certified = next(
        (
            t
            for t in trials
            if t.get("algorithm") == "exact"
            and t.get("proven_optimal")
            and t.get("evaluation", {}).get("feasible")
        ),
        None,
    )
    if certified is None:
        return
    optimum = certified["evaluation"]
    for trial in trials:
        actual = trial.get("evaluation", {})
        if (
            not actual.get("feasible")
            or trial.get("scenario_hash") != certified.get("scenario_hash")
            or trial.get("matrix_hash") != certified.get("matrix_hash")
        ):
            continue
        vehicle_gap = actual["vehicles_used"] - optimum["vehicles_used"]
        trial["exact_reference"] = {
            "vehicles_gap": vehicle_gap,
            "distance_gap_percent": (actual["distance_km"] / optimum["distance_km"] - 1) * 100
            if vehicle_gap == 0 and optimum["distance_km"] > 1e-12
            else None,
            "optimal_vehicles": optimum["vehicles_used"],
            "optimal_distance_km": optimum["distance_km"],
            "note": "Distance gap is defined only at the proven optimal fleet size and nonzero optimal distance.",
        }


def run_experiment(request, progress=None, cancelled=None):
    trials = []
    start = time.perf_counter()
    matrix = build_matrix(request.scenario)
    provenance = {
        "scenario_hash": digest(request.scenario.model_dump()),
        "matrix_hash": matrix.hash,
        "matrix_provenance": matrix.provenance,
        "environment": environment(),
        "solver_version": VERSION,
    }
    # Rotate order per seed to reduce consistent warmup/order advantage.
    cases = []
    for index, seed in enumerate(request.seeds):
        rotated = (
            request.algorithms[index % len(request.algorithms) :]
            + request.algorithms[: index % len(request.algorithms)]
        )
        cases.extend((algorithm, seed) for algorithm in rotated)
    for index, (algorithm, seed) in enumerate(cases):
        if cancelled and cancelled():
            break
        options = RunOptions(
            algorithm=algorithm,
            seed=seed,
            time_limit_seconds=request.time_limit_seconds,
            iterations=request.iterations,
            removal_fraction=request.removal_fraction,
            adaptive=request.adaptive,
            local_improvement=request.local_improvement,
        )

        def report(value, index=index, algorithm=algorithm, seed=seed):
            if progress:
                progress(
                    {
                        "trial_index": index,
                        "trial_count": len(cases),
                        "algorithm": algorithm,
                        "seed": seed,
                        **value,
                    }
                )

        try:
            result = run_once(request.scenario, options, report, cancelled)
            trials.append(result)
        except Exception as exc:
            trials.append(
                {
                    "algorithm": algorithm,
                    "options": options.model_dump(),
                    "status": "error",
                    "error": str(exc)[:500],
                    **provenance,
                }
            )
    groups = []
    annotate_exact_gaps(trials)
    for algorithm in request.algorithms:
        selected = [t for t in trials if t["algorithm"] == algorithm]
        feasible = [t for t in selected if t.get("evaluation", {}).get("feasible")]
        vehicle_counts = [t["evaluation"]["vehicles_used"] for t in feasible]
        min_vehicles = min(vehicle_counts) if vehicle_counts else None
        distances = [
            t["evaluation"]["distance_km"]
            for t in feasible
            if t["evaluation"]["vehicles_used"] == min_vehicles
        ]
        times = [t["solver_time_ms"] for t in selected if "solver_time_ms" in t]
        groups.append(
            {
                "algorithm": algorithm,
                "runs": len(selected),
                "feasible_runs": len(feasible),
                "feasible_rate": len(feasible) / len(selected) if selected else 0,
                "min_vehicles": min_vehicles,
                "max_vehicles": max(vehicle_counts) if vehicle_counts else None,
                "median_distance_at_min_vehicles": statistics.median(distances)
                if distances
                else None,
                "min_distance_at_min_vehicles": min(distances) if distances else None,
                "max_distance_at_min_vehicles": max(distances) if distances else None,
                "distance_stdev_at_min_vehicles": statistics.stdev(distances)
                if len(distances) > 1
                else 0
                if distances
                else None,
                "median_solver_ms": statistics.median(times) if times else None,
            }
        )
    return {
        "kind": "experiment",
        **provenance,
        "scenario": request.scenario.model_dump(),
        "request": request.model_dump(),
        "trials": trials,
        "summary": groups,
        "paired_comparisons": paired_comparisons(trials, request.algorithms, request.seeds),
        "completed_trials": len(trials),
        "planned_trials": len(cases),
        "total_time_ms": (time.perf_counter() - start) * 1000,
        "methodology": "All trials retained. Feasibility first; vehicles then distance. Distance summaries are conditional on each solver’s minimum vehicle count. Wall-time budgets are caps; deterministic baselines may stop early. Seeds do not make time-limited runs bitwise reproducible.",
    }
