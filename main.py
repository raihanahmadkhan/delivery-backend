from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings, get_cors_origins
from routers import optimize, benchmark, data

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "REST API for multi-algorithm vehicle route optimization. "
        "Supports Ant Colony (ACO), Genetic Algorithm (GA), Particle Swarm (PSO), "
        "Nearest Neighbour, and Random baseline solvers."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(optimize.router)
app.include_router(benchmark.router)
app.include_router(data.router)


@app.get("/health", tags=["Health"], summary="Service health check")
async def health_check() -> dict:
    return {
        "status": "ok",
        "version": settings.app_version,
        "algorithms": ["aco", "ga", "pso", "nearest_neighbor", "random"],
    }


@app.get("/", tags=["Health"], include_in_schema=False)
async def root() -> dict:
    return {"message": f"{settings.app_name} — visit /docs for the API reference."}
