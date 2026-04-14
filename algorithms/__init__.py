from .aco import AntColonyOptimizer
from .ga import GeneticAlgorithm
from .pso import ParticleSwarmOptimizer
from .nearest_neighbor import NearestNeighborOptimizer
from .random_route import RandomRouteOptimizer
from .base import BaseOptimizer, OptimizationResult
__all__ = ['AntColonyOptimizer', 'GeneticAlgorithm', 'ParticleSwarmOptimizer', 'NearestNeighborOptimizer', 'RandomRouteOptimizer', 'BaseOptimizer', 'OptimizationResult']
ALGORITHM_REGISTRY: dict = {'aco': AntColonyOptimizer, 'ga': GeneticAlgorithm, 'pso': ParticleSwarmOptimizer, 'nearest_neighbor': NearestNeighborOptimizer, 'random': RandomRouteOptimizer}