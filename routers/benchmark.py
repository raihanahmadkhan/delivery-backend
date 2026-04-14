

from fastapi import APIRouter, HTTPException
from models.schemas import BenchmarkRequest, BenchmarkResponse
from services.benchmark import run_benchmark

router = APIRouter(prefix="/api/benchmark", tags=["Benchmark"])


@router.post("", response_model=BenchmarkResponse, summary="Benchmark multiple algorithms")
async def benchmark(request: BenchmarkRequest) -> BenchmarkResponse:
    
    try:
        return run_benchmark(
            points=request.points,
            algorithms=request.algorithms,
            params=request.params,
            constraints=request.constraints,
            distance_mode=request.distance_mode,
            n_runs=request.n_runs,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Benchmark failed: {exc}") from exc
