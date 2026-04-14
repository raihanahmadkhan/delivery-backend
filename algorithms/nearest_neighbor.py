

import math
from typing import List

from .base import BaseOptimizer, OptimizationResult


class NearestNeighborOptimizer(BaseOptimizer):
    

    def optimize(self) -> OptimizationResult:
        
        start = self._start_timer()

        n = self.n_nodes
        visited = [False] * n
        route = [0]
        visited[0] = True

        for _ in range(n - 1):
            current = route[-1]
            best_next = -1
            best_dist = math.inf

            for j in range(n):
                if not visited[j]:
                    d = self.distance_matrix[current][j]
                    if d < best_dist:
                        best_dist = d
                        best_next = j

            route.append(best_next)
            visited[best_next] = True

        cost = self.route_cost(route)
        penalty, violations = self.constraint_penalty(route)
        total_cost = cost + penalty

        return OptimizationResult(
            route=route,
            cost=total_cost,
            history=[total_cost],   
            time_ms=self._elapsed_ms(start),
            algorithm="Nearest Neighbor",
            violations=violations,
        )
