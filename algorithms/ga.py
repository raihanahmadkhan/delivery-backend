

import random
from typing import List, Tuple

import numpy as np

from .base import BaseOptimizer, OptimizationResult


class GeneticAlgorithm(BaseOptimizer):
    

    def __init__(self, distance_matrix, params=None, constraints=None, callback=None):
        super().__init__(distance_matrix, params, constraints, callback)

        p = self.params
        self.population_size: int  = int(p.get("population_size", 50))
        self.n_generations: int    = int(p.get("n_generations", 100))
        self.crossover_rate: float = float(p.get("crossover_rate", 0.85))
        self.mutation_rate: float  = float(p.get("mutation_rate", 0.15))
        self.tournament_size: int  = int(p.get("tournament_size", 5))
        self.elitism_count: int    = int(p.get("elitism_count", 2))

        
        self.genes: List[int] = list(range(1, self.n_nodes))

    
    
    

    def optimize(self) -> OptimizationResult:
        
        start = self._start_timer()

        
        population: List[List[int]] = [
            self._random_individual() for _ in range(self.population_size)
        ]

        best_individual: List[int] = []
        best_cost: float = float("inf")
        best_violations: int = 0
        history: List[float] = []

        for generation in range(self.n_generations):
            
            fitness_scores = [self._fitness(ind) for ind in population]

            
            gen_best_idx  = int(np.argmin(fitness_scores))
            gen_best_cost = fitness_scores[gen_best_idx]

            if gen_best_cost < best_cost:
                best_cost       = gen_best_cost
                best_individual = population[gen_best_idx][:]
                _, best_violations = self.constraint_penalty(
                    self._to_full_route(best_individual)
                )

            history.append(best_cost)

            
            sorted_pop = [
                ind for _, ind in sorted(
                    zip(fitness_scores, population), key=lambda x: x[0]
                )
            ]

            
            next_gen: List[List[int]] = [
                ind[:] for ind in sorted_pop[: self.elitism_count]
            ]

            
            while len(next_gen) < self.population_size:
                parent_a = self._tournament_select(population, fitness_scores)
                parent_b = self._tournament_select(population, fitness_scores)

                if random.random() < self.crossover_rate:
                    child_a, child_b = self._ox_crossover(parent_a, parent_b)
                else:
                    child_a, child_b = parent_a[:], parent_b[:]

                if random.random() < self.mutation_rate:
                    child_a = self._swap_mutate(child_a)
                if random.random() < self.mutation_rate:
                    child_b = self._swap_mutate(child_b)

                next_gen.append(child_a)
                if len(next_gen) < self.population_size:
                    next_gen.append(child_b)

            population = next_gen

            if self.callback:
                self.callback(generation, best_cost)

        full_route = self._to_full_route(best_individual)

        return OptimizationResult(
            route=full_route,
            cost=best_cost,
            history=history,
            time_ms=self._elapsed_ms(start),
            algorithm="GA",
            violations=best_violations,
        )

    
    
    

    def _random_individual(self) -> List[int]:
        
        ind = self.genes[:]
        random.shuffle(ind)
        return ind

    def _fitness(self, individual: List[int]) -> float:
        
        full_route = self._to_full_route(individual)
        cost = self.route_cost(full_route)
        penalty, _ = self.constraint_penalty(full_route)
        return cost + penalty

    def _to_full_route(self, individual: List[int]) -> List[int]:
        
        return [0] + individual

    def _tournament_select(
        self, population: List[List[int]], fitness: List[float]
    ) -> List[int]:
        
        k = min(self.tournament_size, len(population))
        candidates = random.sample(range(len(population)), k)
        best_idx = min(candidates, key=lambda i: fitness[i])
        return population[best_idx][:]

    def _ox_crossover(
        self, parent_a: List[int], parent_b: List[int]
    ) -> Tuple[List[int], List[int]]:
        
        size = len(parent_a)
        
        a, b = sorted(random.sample(range(size), 2))

        def _build_child(p1: List[int], p2: List[int]) -> List[int]:
            child: List[int] = [None] * size  
            
            child[a : b + 1] = p1[a : b + 1]
            segment_set = set(p1[a : b + 1])
            
            fill_values = [gene for gene in p2 if gene not in segment_set]
            fill_idx = 0
            for i in range(size):
                if child[i] is None:
                    child[i] = fill_values[fill_idx]
                    fill_idx += 1
            return child

        return _build_child(parent_a, parent_b), _build_child(parent_b, parent_a)

    def _swap_mutate(self, individual: List[int]) -> List[int]:
        
        mutant = individual[:]
        if len(mutant) >= 2:
            i, j = random.sample(range(len(mutant)), 2)
            mutant[i], mutant[j] = mutant[j], mutant[i]
        return mutant
