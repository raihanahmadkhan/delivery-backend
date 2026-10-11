"""Reorder remaining onboard stops at one simultaneous decision boundary.

No parcels transfer vehicles, no completed stop moves, and no mid-edge teleporting.
Other vehicles finish their current leg before entering the new decision state.
"""

import random
import time

from . import VERSION
from .evaluator import evaluate, rank
from .experiments import environment
from .matrices import build_matrix, digest
from .models import Scenario, VehicleExecution


def changed_successors(original, proposed):
    def edges(routes):
        return {
            (k, a): b
            for k, route in enumerate(routes)
            for a, b in zip([None] + route, route + [None], strict=True)
        }

    before, after = edges(original), edges(proposed)
    return sum(after.get(key) != value for key, value in before.items())


def run_replan(parent, request, progress=None, cancelled=None):
    if not parent["evaluation"]["feasible"]:
        raise ValueError("Replanning requires a feasible parent solution")
    scenario = Scenario.model_validate(parent["scenario"])
    if scenario.execution:
        raise ValueError(
            "Start a new disruption from a static run; chained disruptions are not supported yet"
        )
    routes = [route[:] for route in parent["routes"]]
    if request.vehicle_index >= len(routes):
        raise ValueError("Selected vehicle is not used in the parent solution")
    target = parent["evaluation"]["vehicles"][request.vehicle_index]
    count = request.completed_stops
    if count > len(routes[request.vehicle_index]):
        raise ValueError("Completed-stop count exceeds the selected route")
    decision_time = target["schedule"][count]["departure"]
    states = []
    for k, route in enumerate(routes):
        schedule = parent["evaluation"]["vehicles"][k]["schedule"]
        if k == request.vehicle_index:
            completed = route[:count]
            ready = decision_time + request.delay_minutes
        else:
            # Finish the next already-started visit before allowing route edits.
            completed_count = sum(stop["arrival"] <= decision_time for stop in schedule[1:-1])
            if (
                completed_count < len(route)
                and schedule[completed_count]["departure"] < decision_time
            ):
                completed_count += 1
            completed = route[:completed_count]
            ready = schedule[completed_count]["departure"]
        states.append(
            VehicleExecution(vehicle_index=k, completed=completed, assigned=route, ready_time=ready)
        )
    scenario.execution = states
    matrix = build_matrix(scenario)
    continued = evaluate(scenario, matrix, routes)
    best_routes, best = routes, continued
    start = time.perf_counter()
    rng = random.Random(request.options.seed)
    history = [
        {
            "iteration": 0,
            "elapsed_ms": 0,
            "feasible": best["feasible"],
            "vehicles_used": best["vehicles_used"],
            "distance_km": best["distance_km"],
            "unserved": 0,
            "operation": "continue existing plan",
        }
    ]
    trace = [{**history[0], "routes": routes, "removed": []}]
    tested = 0
    reason = "iteration_limit"
    for iteration in range(request.options.iterations):
        elapsed = time.perf_counter() - start
        if cancelled and cancelled():
            reason = "cancelled"
            break
        if elapsed >= request.options.time_limit_seconds:
            reason = "time_limit"
            break
        candidate = [route[:] for route in best_routes]
        eligible = [
            k for k, state in enumerate(states) if len(routes[k]) - len(state.completed) >= 2
        ]
        if not eligible:
            reason = "no_unlocked_moves"
            break
        k = rng.choice(eligible)
        locked = len(states[k].completed)
        a, b = rng.sample(range(locked, len(candidate[k])), 2)
        if iteration % 3 == 0:
            low, high = sorted((a, b))
            candidate[k][low : high + 1] = reversed(candidate[k][low : high + 1])
        else:
            node = candidate[k].pop(a)
            candidate[k].insert(b, node)
        changes = changed_successors(routes, candidate)
        if request.change_budget is not None and changes > request.change_budget:
            continue
        tested += 1
        report = evaluate(scenario, matrix, candidate)
        if rank(report) < rank(best):
            best_routes, best = candidate, report
            checkpoint = {
                "iteration": iteration + 1,
                "elapsed_ms": elapsed * 1000,
                "feasible": best["feasible"],
                "vehicles_used": best["vehicles_used"],
                "distance_km": best["distance_km"],
                "unserved": 0,
                "operation": "onboard sequence repair",
            }
            history.append(checkpoint)
            if len(trace) < 240:
                trace.append({**checkpoint, "routes": [r[:] for r in candidate], "removed": []})
        if progress and iteration % 20 == 0:
            progress(
                {
                    "iteration": iteration,
                    "elapsed_ms": elapsed * 1000,
                    "feasible": best["feasible"],
                    "distance_km": best["distance_km"],
                    "vehicles_used": best["vehicles_used"],
                    "routes": best_routes,
                    "history": history[-100:],
                }
            )
    return {
        "kind": "replan",
        "algorithm": "onboard_repair",
        "status": "feasible" if best["feasible"] else "no_feasible_solution_found",
        "termination_reason": reason,
        "proven_optimal": False,
        "routes": best_routes,
        "evaluation": best,
        "history": history,
        "trace": trace,
        "operator_stats": {},
        "solver_time_ms": (time.perf_counter() - start) * 1000,
        "evaluations": tested,
        "scenario": scenario.model_dump(),
        "scenario_hash": digest(scenario.model_dump()),
        "matrix_hash": matrix.hash,
        "matrix_provenance": matrix.provenance,
        "solver_version": VERSION,
        "options": request.options.model_dump(),
        "replan_request": request.model_dump(),
        "environment": environment(),
        "disruption": {
            "decision_time": decision_time,
            "parent_job_id": request.parent_job_id,
            "continued": continued,
            "changed_successors": changed_successors(routes, best_routes),
            "change_budget": request.change_budget,
            "delay_minutes": request.delay_minutes,
            "vehicle_index": request.vehicle_index,
            "semantics": "Onboard assignments fixed; completed prefixes frozen; other vehicles finish their current leg. Changes count altered outgoing successors, including route starts.",
        },
    }
