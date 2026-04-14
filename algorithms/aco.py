import random
import math
from typing import List, Optional, Callable
import numpy as np
from .base import BaseOptimizer, OptimizationResult

class AntColonyOptimizer(BaseOptimizer):

    def __init__(self, distance_matrix, params=None, constraints=None, callback=None):
        super().__init__(distance_matrix, params, constraints, callback)
        p = self.params
        self.n_ants: int = int(p.get('n_ants', 20))
        self.n_iterations: int = int(p.get('n_iterations', 100))
        self.alpha: float = float(p.get('alpha', 1.0))
        self.beta: float = float(p.get('beta', 2.0))
        self.rho: float = float(p.get('rho', 0.5))
        self.q: float = float(p.get('q', 100.0))
        self.elitist_weight: float = float(p.get('elitist_weight', 2.0))
        self.tau_init: float = float(p.get('tau_init', 1.0))
        self.dist = np.array(distance_matrix, dtype=float)
        n = self.n_nodes
        self.tau = np.full((n, n), self.tau_init, dtype=float)
        with np.errstate(divide='ignore'):
            self.eta = np.where(self.dist > 0, 1.0 / self.dist, 0.0)

    def optimize(self) -> OptimizationResult:
        start = self._start_timer()
        best_route: List[int] = []
        best_cost: float = float('inf')
        best_violations: int = 0
        best_details: List[str] = []
        history: List[float] = []
        for iteration in range(self.n_iterations):
            ant_routes: List[List[int]] = []
            ant_costs: List[float] = []
            for _ in range(self.n_ants):
                route = self._construct_tour()
                base_cost = self.route_cost(route)
                penalty, _, _ = self.constraint_penalty(route)
                total_cost = base_cost + penalty
                ant_routes.append(route)
                ant_costs.append(total_cost)
            iter_best_idx = int(np.argmin(ant_costs))
            iter_best_cost = ant_costs[iter_best_idx]
            if iter_best_cost < best_cost:
                best_cost = iter_best_cost
                best_route = ant_routes[iter_best_idx][:]
                _, best_violations, best_details = self.constraint_penalty(best_route)
            history.append(best_cost)
            self.tau *= 1.0 - self.rho
            self.tau = np.clip(self.tau, 1e-10, None)
            for route, cost in zip(ant_routes, ant_costs):
                if cost > 0:
                    deposit = self.q / cost
                    self._deposit_pheromone(route, deposit)
            if best_route and best_cost > 0:
                elite_deposit = self.elitist_weight * (self.q / best_cost)
                self._deposit_pheromone(best_route, elite_deposit)
            if self.callback:
                self.callback(iteration, best_cost)
        return OptimizationResult(route=best_route, cost=self.route_cost(best_route), history=history, time_ms=self._elapsed_ms(start), algorithm='ACO', violations=best_violations, violation_details=best_details)

    def _construct_tour(self) -> List[int]:
        n = self.n_nodes
        visited = [False] * n
        route = [0]
        visited[0] = True
        for _ in range(n - 1):
            current = route[-1]
            tau_row = self.tau[current]
            eta_row = self.eta[current]
            desirability = tau_row ** self.alpha * eta_row ** self.beta
            for v_idx, v in enumerate(visited):
                if v:
                    desirability[v_idx] = 0.0
            total = desirability.sum()
            if total == 0.0:
                unvisited = [j for j in range(n) if not visited[j]]
                next_node = random.choice(unvisited)
            else:
                probabilities = desirability / total
                next_node = int(np.random.choice(n, p=probabilities))
            route.append(next_node)
            visited[next_node] = True
        return route

    def _deposit_pheromone(self, route: List[int], amount: float) -> None:
        for i in range(len(route) - 1):
            a, b = (route[i], route[i + 1])
            self.tau[a][b] += amount
            self.tau[b][a] += amount
        a, b = (route[-1], route[0])
        self.tau[a][b] += amount
        self.tau[b][a] += amount