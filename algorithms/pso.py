import random
from typing import List, Tuple
import numpy as np
from .base import BaseOptimizer, OptimizationResult
Velocity = List[Tuple[int, int]]

class ParticleSwarmOptimizer(BaseOptimizer):

    def __init__(self, distance_matrix, params=None, constraints=None, callback=None):
        super().__init__(distance_matrix, params, constraints, callback)
        p = self.params
        self.n_particles: int = int(p.get('n_particles', 30))
        self.n_iterations: int = int(p.get('n_iterations', 100))
        self.inertia_weight: float = float(p.get('inertia_weight', 0.7))
        self.c1: float = float(p.get('c1', 1.5))
        self.c2: float = float(p.get('c2', 1.5))
        self.max_velocity: int = int(p.get('max_velocity', 4))
        self.delivery_nodes: List[int] = list(range(1, self.n_nodes))

    def optimize(self) -> OptimizationResult:
        start = self._start_timer()
        positions: List[List[int]] = [self._random_position() for _ in range(self.n_particles)]
        velocities: List[Velocity] = [[] for _ in range(self.n_particles)]
        pbest_positions: List[List[int]] = [pos[:] for pos in positions]
        pbest_costs: List[float] = [self._fitness(pos) for pos in positions]
        gbest_idx = int(np.argmin(pbest_costs))
        gbest_position: List[int] = pbest_positions[gbest_idx][:]
        gbest_cost: float = pbest_costs[gbest_idx]
        best_violations: int = 0
        best_details: List[str] = []
        history: List[float] = []
        for iteration in range(self.n_iterations):
            for i in range(self.n_particles):
                current_cost = self._fitness(positions[i])
                if current_cost < pbest_costs[i]:
                    pbest_costs[i] = current_cost
                    pbest_positions[i] = positions[i][:]
                if current_cost < gbest_cost:
                    gbest_cost = current_cost
                    gbest_position = positions[i][:]
                    _, best_violations, best_details = self.constraint_penalty(self._to_full_route(gbest_position))
            history.append(gbest_cost)
            for i in range(self.n_particles):
                r1 = random.random()
                r2 = random.random()
                cognitive_swaps = self._position_difference(positions[i], pbest_positions[i])
                social_swaps = self._position_difference(positions[i], gbest_position)
                new_velocity: Velocity = self._apply_inertia(velocities[i], self.inertia_weight)
                new_velocity += self._filter_swaps(cognitive_swaps, self.c1 * r1)
                new_velocity += self._filter_swaps(social_swaps, self.c2 * r2)
                if len(new_velocity) > self.max_velocity:
                    new_velocity = random.sample(new_velocity, self.max_velocity)
                velocities[i] = new_velocity
                positions[i] = self._apply_velocity(positions[i], velocities[i])
            if self.callback:
                self.callback(iteration, gbest_cost)
        full_route = self._to_full_route(gbest_position)
        return OptimizationResult(route=full_route, cost=self.route_cost(full_route), history=history, time_ms=self._elapsed_ms(start), algorithm='PSO', violations=best_violations, violation_details=best_details)

    def _random_position(self) -> List[int]:
        pos = self.delivery_nodes[:]
        random.shuffle(pos)
        return pos

    def _fitness(self, position: List[int]) -> float:
        full_route = self._to_full_route(position)
        cost = self.route_cost(full_route)
        penalty, _, _ = self.constraint_penalty(full_route)
        return cost + penalty

    def _to_full_route(self, position: List[int]) -> List[int]:
        return [0] + position

    def _position_difference(self, source: List[int], target: List[int]) -> Velocity:
        swaps: Velocity = []
        working = source[:]
        for target_idx, target_val in enumerate(target):
            if working[target_idx] == target_val:
                continue
            source_idx = working.index(target_val, target_idx)
            swaps.append((target_idx, source_idx))
            working[target_idx], working[source_idx] = (working[source_idx], working[target_idx])
        return swaps

    def _apply_velocity(self, position: List[int], velocity: Velocity) -> List[int]:
        new_pos = position[:]
        for i, j in velocity:
            if 0 <= i < len(new_pos) and 0 <= j < len(new_pos):
                new_pos[i], new_pos[j] = (new_pos[j], new_pos[i])
        return new_pos

    def _apply_inertia(self, velocity: Velocity, weight: float) -> Velocity:
        return [(i, j) for i, j in velocity if random.random() < weight]

    def _filter_swaps(self, swaps: Velocity, probability: float) -> Velocity:
        return [(i, j) for i, j in swaps if random.random() < probability]