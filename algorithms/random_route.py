import random
from typing import List
from .base import BaseOptimizer, OptimizationResult

class RandomRouteOptimizer(BaseOptimizer):

    def __init__(self, distance_matrix, params=None, constraints=None, callback=None):
        super().__init__(distance_matrix, params, constraints, callback)
        self.n_trials: int = int(self.params.get('n_trials', 10))

    def optimize(self) -> OptimizationResult:
        start = self._start_timer()
        nodes = list(range(1, self.n_nodes))
        best_route: List[int] = []
        best_cost = float('inf')
        history: List[float] = []
        for _ in range(self.n_trials):
            random.shuffle(nodes)
            route = [0] + nodes[:]
            cost = self.route_cost(route)
            penalty, _, _ = self.constraint_penalty(route)
            total = cost + penalty
            if total < best_cost:
                best_cost = total
                best_route = route[:]
            history.append(best_cost)
        _, violations, details = self.constraint_penalty(best_route)
        return OptimizationResult(route=best_route, cost=self.route_cost(best_route), history=history, time_ms=self._elapsed_ms(start), algorithm='Random', violations=violations, violation_details=details)