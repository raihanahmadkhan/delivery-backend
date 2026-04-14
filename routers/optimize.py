

from fastapi import APIRouter, HTTPException
from models.schemas import OptimizeRequest, OptimizeResponse
from services.optimizer import run_optimization

router = APIRouter(prefix="/api/optimize", tags=["Optimize"])


@router.post("", response_model=OptimizeResponse, summary="Run a single optimization algorithm")
async def optimize(request: OptimizeRequest) -> OptimizeResponse:
    
    try:
        return run_optimization(
            points=request.points,
            algorithm=request.algorithm,
            params=request.params,
            constraints=request.constraints,
            distance_mode=request.distance_mode,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Optimization failed: {exc}") from exc
