from typing import List, Optional, Callable
from algorithms import ALGORITHM_REGISTRY, OptimizationResult
from models.schemas import DeliveryPoint, Constraints, OptimizeResponse
from utils.distance import build_distance_matrix

def run_optimization(points: List[DeliveryPoint], algorithm: str, params: dict, constraints: Constraints, distance_mode: str='haversine', callback: Optional[Callable]=None) -> OptimizeResponse:
    if algorithm not in ALGORITHM_REGISTRY:
        raise ValueError(f"Unknown algorithm '{algorithm}'. Available: {list(ALGORITHM_REGISTRY.keys())}")
    point_dicts = [p.model_dump() for p in points]
    distance_matrix = build_distance_matrix(point_dicts, mode=distance_mode)
    constraint_dict = _build_constraint_dict(points, constraints)
    AlgorithmClass = ALGORITHM_REGISTRY[algorithm]
    optimizer = AlgorithmClass(distance_matrix=distance_matrix, params=params, constraints=constraint_dict, callback=callback)
    result: OptimizationResult = optimizer.optimize()
    names = [p.name or f'Node {p.id}' for p in points]
    route_names = [names[i] for i in result.route if i < len(names)]
    return OptimizeResponse(algorithm=result.algorithm, route=result.route, route_names=route_names, cost=result.cost, history=result.history, time_ms=result.time_ms, violations=result.violations, violation_details=result.violation_details, vehicle_routes=result.vehicle_routes)

def _build_constraint_dict(points: List[DeliveryPoint], constraints: Constraints) -> dict:
    return {'demands': [p.demand for p in points], 'time_windows': [(p.time_window_start, p.time_window_end) for p in points], 'vehicle_capacity': constraints.vehicle_capacity, 'max_distance': constraints.max_distance, 'num_vehicles': constraints.num_vehicles}