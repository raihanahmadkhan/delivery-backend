from typing import List, Optional
from models.schemas import DeliveryPoint, Constraints, BenchmarkEntry, BenchmarkResponse
from services.optimizer import run_optimization

def run_benchmark(points: List[DeliveryPoint], algorithms: List[str], params: dict, constraints: Constraints, distance_mode: str='haversine', n_runs: int=1) -> BenchmarkResponse:
    results: List[BenchmarkEntry] = []
    for algo in algorithms:
        best_response = None
        for _ in range(n_runs):
            response = run_optimization(points=points, algorithm=algo, params=params, constraints=constraints, distance_mode=distance_mode)
            if best_response is None or response.cost < best_response.cost:
                best_response = response
        if best_response is not None:
            results.append(BenchmarkEntry(algorithm=best_response.algorithm, route=best_response.route, route_names=best_response.route_names, cost=best_response.cost, history=best_response.history, time_ms=best_response.time_ms, violations=best_response.violations, violation_details=best_response.violation_details, improvement_vs_random=None))
    random_result = next((r for r in results if r.algorithm.lower() == 'random'), None)
    if random_result and random_result.cost > 0:
        for entry in results:
            if entry.algorithm.lower() != 'random':
                improvement = (random_result.cost - entry.cost) / random_result.cost * 100
                entry.improvement_vs_random = round(improvement, 2)
    results.sort(key=lambda r: r.cost)
    summary = _build_summary(results)
    return BenchmarkResponse(results=results, summary=summary)

def _build_summary(results: List[BenchmarkEntry]) -> dict:
    if not results:
        return {}
    costs = [r.cost for r in results]
    times = [r.time_ms for r in results]
    best = results[0]
    worst = results[-1]
    return {'best_algorithm': best.algorithm, 'worst_algorithm': worst.algorithm, 'best_cost': round(best.cost, 4), 'worst_cost': round(worst.cost, 4), 'cost_range': round(worst.cost - best.cost, 4), 'avg_cost': round(sum(costs) / len(costs), 4), 'total_time_ms': round(sum(times), 2), 'algorithms_run': len(results)}