from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional, Callable
import time

@dataclass
class OptimizationResult:
    route: List[int]
    cost: float
    history: List[float]
    time_ms: float
    algorithm: str
    violations: int = 0
    violation_details: List[str] = field(default_factory=list)
    vehicle_routes: List[List[int]] = field(default_factory=list)

class BaseOptimizer(ABC):

    def __init__(self, distance_matrix: List[List[float]], params: Optional[dict]=None, constraints: Optional[dict]=None, callback: Optional[Callable[[int, float], None]]=None):
        self.distance_matrix = distance_matrix
        self.n_nodes = len(distance_matrix)
        self.params = params or {}
        self.constraints = constraints or {}
        self.callback = callback

    @abstractmethod
    def optimize(self) -> OptimizationResult:
        ...

    def route_cost(self, route: List[int]) -> float:
        total = 0.0
        for i in range(len(route) - 1):
            total += self.distance_matrix[route[i]][route[i + 1]]
        total += self.distance_matrix[route[-1]][route[0]]
        return total

    def constraint_penalty(self, route: List[int]) -> tuple[float, int, List[str]]:
        if not self.constraints:
            return (0.0, 0, [])
        penalty = 0.0
        violations = 0
        details = []
        demands = self.constraints.get('demands', [])
        capacity = self.constraints.get('vehicle_capacity', float('inf'))
        time_windows = self.constraints.get('time_windows', [])
        max_dist = self.constraints.get('max_distance', float('inf'))
        if demands and capacity < float('inf'):
            total_demand = sum((demands[n] for n in route if n < len(demands)))
            if total_demand > capacity:
                excess = total_demand - capacity
                penalty += excess * 1000
                violations += 1
                details.append(f'Capacity exceeded by {excess:.1f} units')
        if time_windows:
            current_time = 0.0
            prev = route[0]
            for node in route[1:]:
                travel = self.distance_matrix[prev][node]
                current_time += travel
                if node < len(time_windows):
                    tw_start, tw_end = time_windows[node]
                    if current_time < tw_start:
                        current_time = tw_start
                    elif current_time > tw_end:
                        lateness = current_time - tw_end
                        penalty += lateness * 500
                        violations += 1
                        details.append(f'Arrived at Node {node} late by {lateness:.1f} mins')
                prev = node
        if max_dist < float('inf'):
            dist = self.route_cost(route)
            if dist > max_dist:
                penalty += (dist - max_dist) * 200
                violations += 1
                details.append(f'Max distance exceeded by {dist - max_dist:.1f} km')
        return (penalty, violations, details)

    def _start_timer(self) -> float:
        return time.perf_counter()

    def _elapsed_ms(self, start: float) -> float:
        return (time.perf_counter() - start) * 1000