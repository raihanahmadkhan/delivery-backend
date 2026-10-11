"""A deliberately plain, solver-independent forward/backward schedule checker."""

from collections import Counter

from .matrices import Matrix
from .models import Scenario

EPS = 1e-7


def evaluate(scenario: Scenario, matrix: Matrix, routes: list[list[str]]) -> dict:
    nodes = {node.id: node for node in scenario.nodes}
    customers = set(nodes) - {scenario.depot_id}
    depot = nodes[scenario.depot_id]
    seen = Counter(node for route in routes for node in route)
    unserved = sorted(customers - set(seen))
    violations = []
    vehicles = []
    excess = 0.0

    def issue(kind, message, vehicle=None, node=None, amount=0.0):
        nonlocal excess
        violations.append(
            {
                "kind": kind,
                "message": message,
                "vehicle_index": vehicle,
                "node_id": node,
                "amount": round(amount, 6),
            }
        )
        excess += max(0, amount)

    for node_id, count in seen.items():
        if node_id not in customers:
            issue("invalid_node", f"{node_id} is not a customer")
        if count != 1:
            issue("duplicate", f"{node_id} is visited {count} times", node=node_id)
    if len(routes) > scenario.fleet.count:
        issue(
            "fleet",
            "More routes than available vehicles",
            amount=len(routes) - scenario.fleet.count,
        )
    execution = {state.vehicle_index: state for state in scenario.execution}
    for k, route in enumerate(routes):
        if not route:
            if k in execution and execution[k].assigned:
                issue("assignment", "An active vehicle lost its assigned deliveries", k)
            continue
        if any(node not in customers for node in route):
            continue
        state = execution.get(k)
        if scenario.execution and (state is None or set(route) != set(state.assigned)):
            issue("assignment", "Onboard deliveries cannot transfer between vehicles", k)
        if state and route[: len(state.completed)] != state.completed:
            issue("locked_prefix", "Completed visits were changed", k)
        load = sum(nodes[node].demand for node in route)
        initial_load = load
        if load > scenario.fleet.capacity + EPS:
            issue("capacity", "Vehicle capacity exceeded", k, amount=load - scenario.fleet.capacity)
        current_time = max(scenario.fleet.start_time, depot.window_start)
        initial_departure = current_time
        if state and not state.completed:
            current_time = max(current_time, state.ready_time)
        if current_time > depot.window_end + EPS:
            issue(
                "depot_window",
                "Departure is after the depot closes",
                k,
                depot.id,
                current_time - depot.window_end,
            )
        distance, driving, waiting, service = 0.0, 0.0, 0.0, 0.0
        previous = depot.id
        schedule = [
            {
                "node_id": depot.id,
                "arrival": initial_departure,
                "service_start": initial_departure,
                "departure": current_time,
                "waiting": 0.0,
                "travel_minutes": 0.0,
                "service_minutes": 0.0,
                "load_remaining": load,
                "slack": 0.0,
                "disruption_minutes": current_time - initial_departure,
            }
        ]
        for position, node_id in enumerate(route):
            node = nodes[node_id]
            edge_distance, travel = matrix.edge(previous, node_id)
            if edge_distance is None or travel is None:
                issue("unreachable", f"No path from {previous} to {node_id}", k, node_id)
                edge_distance, travel = 0.0, 0.0
            distance += edge_distance
            driving += travel
            arrival = current_time + travel
            start = max(arrival, node.window_start)
            wait = start - arrival
            waiting += wait
            service += node.service_minutes
            if start > node.window_end + EPS:
                issue(
                    "time_window",
                    f"{node.name or node_id}: service starts after its deadline",
                    k,
                    node_id,
                    start - node.window_end,
                )
            current_time = start + node.service_minutes
            delay = 0.0
            if state and position + 1 == len(state.completed):
                delay = max(0.0, state.ready_time - current_time)
                current_time += delay
            load -= node.demand
            schedule.append(
                {
                    "node_id": node_id,
                    "arrival": arrival,
                    "service_start": start,
                    "departure": current_time,
                    "waiting": wait,
                    "travel_minutes": travel,
                    "service_minutes": node.service_minutes,
                    "load_remaining": max(0, load),
                    "slack": 0.0,
                    "disruption_minutes": delay,
                }
            )
            previous = node_id
        edge_distance, travel = matrix.edge(previous, depot.id)
        if edge_distance is None or travel is None:
            issue("unreachable", f"No return path from {previous} to depot", k, depot.id)
            edge_distance, travel = 0.0, 0.0
        distance += edge_distance
        driving += travel
        current_time += travel
        return_limit = min(scenario.fleet.end_time, depot.window_end)
        if current_time > return_limit + EPS:
            issue(
                "return_deadline",
                "Vehicle returns after the depot/shift deadline",
                k,
                depot.id,
                current_time - return_limit,
            )
        if (
            scenario.fleet.max_distance_km is not None
            and distance > scenario.fleet.max_distance_km + EPS
        ):
            issue(
                "distance_limit",
                "Vehicle exceeds its maximum route distance",
                k,
                amount=distance - scenario.fleet.max_distance_km,
            )
        schedule.append(
            {
                "node_id": depot.id,
                "arrival": current_time,
                "service_start": current_time,
                "departure": current_time,
                "waiting": 0.0,
                "travel_minutes": travel,
                "service_minutes": 0.0,
                "load_remaining": 0.0,
                "slack": return_limit - current_time,
                "disruption_minutes": 0.0,
            }
        )
        latest = return_limit
        next_node = depot.id
        for stop in reversed(schedule[1:-1]):
            node = nodes[stop["node_id"]]
            _, next_travel = matrix.edge(node.id, next_node)
            latest = min(
                node.window_end,
                latest - (next_travel or 0) - node.service_minutes - stop["disruption_minutes"],
            )
            stop["slack"] = latest - stop["service_start"]
            next_node = node.id
        vehicles.append(
            {
                "vehicle_index": k,
                "customers": route[:],
                "route": [depot.id] + route + [depot.id],
                "distance_km": distance,
                "driving_minutes": driving,
                "waiting_minutes": waiting,
                "service_minutes": service,
                "return_time": current_time,
                "initial_load": initial_load,
                "capacity": scenario.fleet.capacity,
                "schedule": schedule,
            }
        )
    for node_id in unserved:
        issue("unserved", f"{nodes[node_id].name or node_id} is not served", node=node_id)
    total_distance = sum(vehicle["distance_km"] for vehicle in vehicles)
    return {
        "feasible": not violations,
        "vehicles_used": len(vehicles),
        "distance_km": total_distance,
        "driving_minutes": sum(v["driving_minutes"] for v in vehicles),
        "waiting_minutes": sum(v["waiting_minutes"] for v in vehicles),
        "service_minutes": sum(v["service_minutes"] for v in vehicles),
        "unserved": unserved,
        "violations": violations,
        "excess": excess,
        "vehicles": vehicles,
        "objective": [len(vehicles), total_distance],
    }


def rank(evaluation: dict):
    """Search ordering only. Final feasibility is always checked independently."""
    hard = sum(v["kind"] != "unserved" for v in evaluation["violations"])
    return (
        len(evaluation["unserved"]),
        hard,
        evaluation["excess"],
        evaluation["vehicles_used"],
        evaluation["distance_km"],
    )
