"""The fast insertion checker is deliberately separate from the output validator.

Every retained solution is re-evaluated by evaluator.evaluate before publication.
"""

import itertools
import math
import random
import time

from .evaluator import evaluate, rank
from .matrices import Matrix
from .models import RunOptions, Scenario


class SearchStopped(Exception):
    def __init__(self, reason):
        self.reason = reason


def compact(routes):
    return [route[:] for route in routes if route]


class Search:
    def __init__(
        self, scenario: Scenario, matrix: Matrix, options: RunOptions, progress=None, cancelled=None
    ):
        self.scenario, self.matrix, self.options = scenario, matrix, options
        self.nodes = {node.id: node for node in scenario.nodes}
        self.customers = [n.id for n in scenario.nodes if n.id != scenario.depot_id]
        self.rng = random.Random(options.seed)
        self.start = time.perf_counter()
        self.progress, self.cancelled = progress, cancelled
        self.last_signal = 0.0
        self.evaluations, self.iteration = 0, 0
        self.best_routes = []
        self.best = evaluate(scenario, matrix, [])
        self.history, self.trace = [], []
        self.operator_stats = {}
        self.proven_optimal = False
        self.proven_infeasible = False
        self.consider([], "initial", force=True)

    def elapsed(self):
        return time.perf_counter() - self.start

    def check(self):
        elapsed = self.elapsed()
        if elapsed - self.last_signal >= 0.2:
            self.last_signal = elapsed
            if self.cancelled and self.cancelled():
                raise SearchStopped("cancelled")
            if self.progress:
                self.progress(self.progress_payload())
        if elapsed >= self.options.time_limit_seconds:
            raise SearchStopped("time_limit")

    def progress_payload(self):
        return {
            "iteration": self.iteration,
            "evaluations": self.evaluations,
            "elapsed_ms": round(self.elapsed() * 1000, 2),
            "feasible": self.best["feasible"],
            "vehicles_used": self.best["vehicles_used"],
            "distance_km": self.best["distance_km"],
            "unserved": len(self.best["unserved"]),
            "routes": self.best_routes,
            "history": self.history[-100:],
        }

    def consider(self, routes, operation, removed=None, force=False):
        evaluation = evaluate(self.scenario, self.matrix, routes)
        improved = rank(evaluation) < rank(self.best)
        if improved or force:
            self.best_routes = [route[:] for route in routes]
            self.best = evaluation
            point = {
                "iteration": self.iteration,
                "elapsed_ms": round(self.elapsed() * 1000, 3),
                "distance_km": evaluation["distance_km"],
                "vehicles_used": evaluation["vehicles_used"],
                "feasible": evaluation["feasible"],
                "unserved": len(evaluation["unserved"]),
                "operation": operation,
            }
            self.history.append(point)
            self.trace.append(
                {
                    **point,
                    "routes": [r[:] for r in routes],
                    "removed": removed or [],
                    "violations": evaluation["violations"][:12],
                }
            )
            if len(self.trace) > 240:
                self.trace = self.trace[:1] + self.trace[1:-1:2] + self.trace[-1:]
            if len(self.history) > 500:
                self.history = self.history[:1] + self.history[1:-1:2] + self.history[-1:]
        return evaluation, improved

    def route_distance(self, route):
        path = [self.scenario.depot_id] + route + [self.scenario.depot_id]
        edges = [self.matrix.edge(a, b)[0] for a, b in zip(path, path[1:], strict=False)]
        return float("inf") if any(edge is None for edge in edges) else sum(edges)

    def admissible(self, route):
        """Fast candidate screening; final output uses the independent checker."""
        self.evaluations += 1
        self.check()
        if len(set(route)) != len(route) or any(node not in self.customers for node in route):
            return False
        fleet = self.scenario.fleet
        if sum(self.nodes[n].demand for n in route) > fleet.capacity + 1e-7:
            return False
        depot = self.nodes[self.scenario.depot_id]
        now = max(fleet.start_time, depot.window_start)
        if now > depot.window_end + 1e-7:
            return False
        previous, distance = depot.id, 0.0
        for node_id in route:
            d, travel = self.matrix.edge(previous, node_id)
            if d is None or travel is None:
                return False
            node = self.nodes[node_id]
            now = max(now + travel, node.window_start)
            if now > node.window_end + 1e-7:
                return False
            now += node.service_minutes
            distance += d
            previous = node_id
        d, travel = self.matrix.edge(previous, depot.id)
        if d is None or travel is None:
            return False
        return now + travel <= min(fleet.end_time, depot.window_end) + 1e-7 and (
            fleet.max_distance_km is None or distance + d <= fleet.max_distance_km + 1e-7
        )


def repair(search: Search, routes, missing, regret=True, publish=False):
    routes = compact(routes)
    remaining = list(missing)
    search.rng.shuffle(remaining)
    while remaining:
        search.check()
        choices = []
        for node in remaining:
            placements = []
            for k in range(min(len(routes) + 1, search.scenario.fleet.count)):
                route = routes[k] if k < len(routes) else []
                old_distance = search.route_distance(route) if route else 0
                for position in range(len(route) + 1):
                    candidate = route[:position] + [node] + route[position:]
                    if search.admissible(candidate):
                        delta = (
                            search.route_distance(candidate) - old_distance
                            if math.isfinite(old_distance)
                            else search.route_distance(candidate)
                        )
                        placements.append((int(not route), delta, k, position))
            if placements:
                placements.sort()
                first = placements[0]
                if regret:
                    # A unique feasible placement is urgent.
                    urgency = float("inf") if len(placements) == 1 else placements[1][1] - first[1]
                    choices.append(((first[0], -urgency, first[1]), node, first))
                else:
                    choices.append(((first[0], first[1]), node, first))
        if not choices:
            break
        _, node, (_, _, k, position) = min(choices, key=lambda choice: choice[0])
        if k == len(routes):
            routes.append([])
        routes[k].insert(position, node)
        remaining.remove(node)
        if publish:
            search.consider(routes, "regret insertion" if regret else "cheapest insertion")
    return routes


def relocate(search, routes, current):
    for a, route in enumerate(routes):
        for position, node in enumerate(route):
            shortened = route[:position] + route[position + 1 :]
            for b in range(min(len(routes) + 1, search.scenario.fleet.count)):
                target = shortened if a == b else (routes[b] if b < len(routes) else [])
                for insertion in range(len(target) + 1):
                    search.check()
                    changed = target[:insertion] + [node] + target[insertion:]
                    if a == b and changed == route:
                        continue
                    if not search.admissible(changed) or (
                        a != b and shortened and not search.admissible(shortened)
                    ):
                        continue
                    proposal = [r[:] for r in routes]
                    proposal[a] = shortened
                    if b == len(proposal):
                        proposal.append(changed)
                    else:
                        proposal[b] = changed
                    proposal = compact(proposal)
                    objective = (len(proposal), sum(search.route_distance(r) for r in proposal))
                    if objective[0] < current[0] or (
                        objective[0] == current[0] and objective[1] < current[1] - 1e-8
                    ):
                        return proposal
    return None


def two_opt(search, routes, distances):
    # Evaluate the entire reversed route: arcs may be directed, so no symmetric shortcut.
    for a, route in enumerate(routes):
        for left in range(len(route) - 1):
            for right in range(left + 1, len(route)):
                candidate = route[:left] + route[left : right + 1][::-1] + route[right + 1 :]
                if (
                    search.admissible(candidate)
                    and search.route_distance(candidate) < distances[a] - 1e-8
                ):
                    proposal = [r[:] for r in routes]
                    proposal[a] = candidate
                    return proposal
    return None


def exchange(search, routes, distances):
    for a in range(len(routes)):
        for b in range(a + 1, len(routes)):
            for i in range(len(routes[a])):
                for j in range(len(routes[b])):
                    first, second = routes[a][:], routes[b][:]
                    first[i], second[j] = second[j], first[i]
                    if (
                        search.admissible(first)
                        and search.admissible(second)
                        and search.route_distance(first) + search.route_distance(second)
                        < distances[a] + distances[b] - 1e-8
                    ):
                        proposal = [r[:] for r in routes]
                        proposal[a], proposal[b] = first, second
                        return proposal
    return None


def improve(search: Search, routes, max_moves=100):
    routes = compact(routes)
    if not evaluate(search.scenario, search.matrix, routes)["feasible"]:
        return routes
    for _ in range(max_moves):
        search.check()
        distances = [search.route_distance(route) for route in routes]
        accepted = relocate(search, routes, (len(routes), sum(distances)))
        if accepted is None:
            accepted = two_opt(search, routes, distances)
        if accepted is None:
            accepted = exchange(search, routes, distances)
        if accepted is None:
            break
        routes = accepted
        search.consider(routes, "local improvement")
    return routes


def destroy(search, routes, operator):
    present = [node for route in routes for node in route]
    if not present:
        return [], []
    count = max(1, math.ceil(len(present) * search.options.removal_fraction))
    if operator == "random":
        removed = search.rng.sample(present, count)
    elif operator == "related":
        anchor = search.rng.choice(present)
        removed = sorted(
            present,
            key=lambda node: (
                search.matrix.edge(anchor, node)[0]
                if search.matrix.edge(anchor, node)[0] is not None
                else float("inf")
            ),
        )[:count]
    elif operator == "route":
        removed = search.rng.choice([r for r in routes if r])[:]
    else:
        savings = []
        for route in routes:
            old = search.route_distance(route)
            for index, node in enumerate(route):
                savings.append(
                    (old - search.route_distance(route[:index] + route[index + 1 :]), node)
                )
        removed = [node for _, node in sorted(savings, reverse=True)[:count]]
    removed_set = set(removed)
    return compact(
        [[node for node in route if node not in removed_set] for route in routes]
    ), removed


def alns(search: Search, routes):
    current = [route[:] for route in routes]
    current_eval = evaluate(search.scenario, search.matrix, current)
    operators = ["random", "related", "costly", "route"]
    weights = dict.fromkeys(operators, 1.0)
    search.operator_stats = {
        operator: {"uses": 0, "accepted": 0, "improvements": 0, "weight": 1.0}
        for operator in operators
    }
    for iteration in range(search.options.iterations):
        search.iteration = iteration + 1
        search.check()
        operator = search.rng.choices(operators, weights=[weights[op] for op in operators])[0]
        partial, removed = destroy(search, current, operator)
        missing = set(search.customers) - {node for route in partial for node in route}
        proposal = repair(search, partial, sorted(missing), regret=bool(search.rng.getrandbits(1)))
        proposal_eval, improved = search.consider(proposal, f"{operator} removal + repair", removed)
        if search.options.local_improvement and iteration % 8 == 0 and proposal_eval["feasible"]:
            best_before_local = rank(search.best)
            proposal = improve(search, proposal, max_moves=2)
            proposal_eval, _ = search.consider(proposal, "repair + local search", removed)
            improved = improved or rank(search.best) < best_before_local
        candidate_rank, current_rank = rank(proposal_eval), rank(current_eval)
        accept = candidate_rank <= current_rank
        if not accept and candidate_rank[:4] == current_rank[:4]:
            temperature = max(
                0.001,
                current_eval["distance_km"] * 0.04 * (1 - iteration / search.options.iterations),
            )
            accept = search.rng.random() < math.exp(
                -min(700, (candidate_rank[-1] - current_rank[-1]) / temperature)
            )
        if accept:
            current, current_eval = proposal, proposal_eval
        stats = search.operator_stats[operator]
        stats["uses"] += 1
        stats["accepted"] += int(accept)
        stats["improvements"] += int(improved)
        if search.options.adaptive:
            reward = 6.0 if improved else (1.5 if accept else 0.3)
            weights[operator] = max(0.1, 0.85 * weights[operator] + 0.15 * reward)
        stats["weight"] = round(weights[operator], 4)


def exact(search: Search):
    """Enumerate feasible ordered subsets; dynamic-program the best partition.

    Completion certifies the lexicographic optimum for <=8 customers. Interrupting
    enumeration does not certify either optimality or infeasibility.
    """
    customers = search.customers
    if len(customers) > 8:
        raise ValueError("The exhaustive reference supports at most 8 customers")
    best_subsets = {}
    for size in range(1, len(customers) + 1):
        for subset in itertools.combinations(range(len(customers)), size):
            mask = sum(1 << i for i in subset)
            for ordering in itertools.permutations(subset):
                route = [customers[index] for index in ordering]
                if search.admissible(route):
                    distance = search.route_distance(route)
                    if mask not in best_subsets or distance < best_subsets[mask][0]:
                        best_subsets[mask] = (distance, route)
    full = (1 << len(customers)) - 1
    dp = {0: ((0, 0.0), [])}
    for mask in range(1, full + 1):
        search.check()
        anchor = mask & -mask
        subset = mask
        while subset:
            if subset & anchor and subset in best_subsets and mask ^ subset in dp:
                prior_objective, prior_routes = dp[mask ^ subset]
                distance, route = best_subsets[subset]
                objective = (prior_objective[0] + 1, prior_objective[1] + distance)
                if objective[0] <= search.scenario.fleet.count and (
                    mask not in dp or objective < dp[mask][0]
                ):
                    dp[mask] = (objective, prior_routes + [route])
            subset = (subset - 1) & mask
    if full in dp:
        search.consider(dp[full][1], "exhaustive subset partition", force=True)
        search.proven_optimal = True
    else:
        search.proven_infeasible = True


def solve(scenario, matrix, options, progress=None, cancelled=None):
    if scenario.execution:
        raise ValueError("Execution states must be solved through the replanning endpoint")
    search = Search(scenario, matrix, options, progress, cancelled)
    reason = "completed"
    try:
        initial = repair(
            search, [], search.customers, regret=options.algorithm != "greedy", publish=True
        )
        search.consider(initial, "construction complete")
        if options.algorithm == "local_search":
            improve(search, initial)
        elif options.algorithm == "alns":
            alns(search, initial)
            reason = "iteration_limit"
        elif options.algorithm == "exact":
            exact(search)
        elif options.algorithm == "ortools":
            from .reference import ortools_solve

            ortools_solve(search)
    except SearchStopped as exc:
        reason = exc.reason
    return finish(search, reason)


def finish(search, reason):
    validated = evaluate(search.scenario, search.matrix, search.best_routes)
    status = (
        "optimal"
        if search.proven_optimal
        else (
            "proven_infeasible"
            if search.proven_infeasible
            else ("feasible" if validated["feasible"] else "no_feasible_solution_found")
        )
    )
    return {
        "algorithm": search.options.algorithm,
        "status": status,
        "termination_reason": reason,
        "proven_optimal": search.proven_optimal,
        "routes": search.best_routes,
        "evaluation": validated,
        "history": search.history,
        "trace": search.trace,
        "operator_stats": search.operator_stats,
        "solver_time_ms": round(search.elapsed() * 1000, 3),
        "evaluations": search.evaluations,
        "iterations": search.iteration,
    }
