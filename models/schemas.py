

from typing import List, Optional, Literal
from pydantic import BaseModel, Field, field_validator




class DeliveryPoint(BaseModel):
    
    id: int = Field(..., description="Unique node identifier. 0 = depot.")
    name: str = Field(default="", description="Human-readable label.")
    latitude: float  = Field(..., ge=-90,  le=90,  description="GPS latitude.")
    longitude: float = Field(..., ge=-180, le=180, description="GPS longitude.")
    demand: float    = Field(default=0.0,  ge=0,   description="Load/demand units.")
    time_window_start: float = Field(default=0.0,    description="Earliest service time (minutes).")
    time_window_end:   float = Field(default=1440.0, description="Latest service time (minutes).")

    @field_validator("time_window_end")
    @classmethod
    def end_after_start(cls, v: float, info) -> float:
        start = info.data.get("time_window_start", 0.0)
        if v < start:
            raise ValueError("time_window_end must be >= time_window_start")
        return v




class ACOParams(BaseModel):
    n_ants: int         = Field(default=20,  ge=1,  description="Number of ants per iteration.")
    n_iterations: int   = Field(default=100, ge=1,  description="Number of ACO iterations.")
    alpha: float        = Field(default=1.0, gt=0,  description="Pheromone exponent α.")
    beta: float         = Field(default=2.0, gt=0,  description="Heuristic exponent β.")
    rho: float          = Field(default=0.5, gt=0, lt=1, description="Evaporation rate ρ.")
    q: float            = Field(default=100.0, gt=0, description="Pheromone deposit constant Q.")
    elitist_weight: float = Field(default=2.0, ge=0, description="Elitist ant deposit multiplier.")


class GAParams(BaseModel):
    population_size: int  = Field(default=50,  ge=4,  description="Population size.")
    n_generations: int    = Field(default=100, ge=1,  description="Number of generations.")
    crossover_rate: float = Field(default=0.85, ge=0, le=1, description="OX crossover probability.")
    mutation_rate: float  = Field(default=0.15, ge=0, le=1, description="Swap mutation probability.")
    tournament_size: int  = Field(default=5,   ge=2,  description="Tournament selection size.")
    elitism_count: int    = Field(default=2,   ge=0,  description="Elite individuals preserved.")


class PSOParams(BaseModel):
    n_particles: int    = Field(default=30,  ge=2,  description="Swarm size.")
    n_iterations: int   = Field(default=100, ge=1,  description="Number of iterations.")
    inertia_weight: float = Field(default=0.7, ge=0, le=1, description="Inertia weight ω.")
    c1: float           = Field(default=1.5, ge=0,  description="Cognitive acceleration c1.")
    c2: float           = Field(default=1.5, ge=0,  description="Social acceleration c2.")
    max_velocity: int   = Field(default=4,   ge=1,  description="Max swap operations per velocity.")




class Constraints(BaseModel):
    num_vehicles: int      = Field(default=1, ge=1,   description="Number of vehicles in the fleet.")
    vehicle_capacity: float = Field(default=float("inf"), ge=0, description="Max demand per vehicle.")
    max_distance: float    = Field(default=float("inf"), ge=0, description="Max distance per vehicle.")




class OptimizeRequest(BaseModel):
    
    points: List[DeliveryPoint] = Field(
        ..., min_length=2, description="List of delivery points. First point is treated as depot."
    )
    algorithm: Literal["aco", "ga", "pso", "nearest_neighbor", "random"] = Field(
        default="aco", description="Which algorithm to run."
    )
    params: dict = Field(
        default_factory=dict,
        description="Algorithm hyper-parameters (merged with defaults).",
    )
    constraints: Constraints = Field(
        default_factory=Constraints,
        description="VRP constraints (capacity, time windows, vehicles).",
    )
    distance_mode: Literal["haversine", "euclidean"] = Field(
        default="haversine",
        description="haversine = real GPS distances; euclidean = abstract x,y.",
    )


class OptimizeResponse(BaseModel):
    
    algorithm: str
    route: List[int]           = Field(..., description="Ordered node indices.")
    route_names: List[str]     = Field(..., description="Human-readable node names in route order.")
    cost: float                = Field(..., description="Total route distance.")
    history: List[float]       = Field(..., description="Best cost per iteration (convergence data).")
    time_ms: float             = Field(..., description="Execution time in milliseconds.")
    violations: int            = Field(..., description="Number of constraint violations.")
    vehicle_routes: List[List[int]] = Field(default_factory=list)




class BenchmarkRequest(BaseModel):
    
    points: List[DeliveryPoint] = Field(..., min_length=2)
    algorithms: List[Literal["aco", "ga", "pso", "nearest_neighbor", "random"]] = Field(
        default=["aco", "ga", "pso", "nearest_neighbor", "random"],
        description="Algorithms to include in the benchmark.",
    )
    params: dict = Field(
        default_factory=dict,
        description="Shared params applied to all algorithms (algorithm-specific keys respected).",
    )
    constraints: Constraints = Field(default_factory=Constraints)
    distance_mode: Literal["haversine", "euclidean"] = Field(default="haversine")
    n_runs: int = Field(
        default=1, ge=1, le=10,
        description="Number of independent runs per algorithm; best result is returned.",
    )


class BenchmarkEntry(BaseModel):
    algorithm: str
    route: List[int]
    route_names: List[str]
    cost: float
    history: List[float]
    time_ms: float
    violations: int
    improvement_vs_random: Optional[float] = Field(
        None, description="% distance reduction compared to Random baseline."
    )


class BenchmarkResponse(BaseModel):
    results: List[BenchmarkEntry]
    summary: dict = Field(
        default_factory=dict,
        description="Aggregate stats: best algorithm, worst algorithm, range, etc.",
    )




class PresetsListResponse(BaseModel):
    available: List[str]


class PointsResponse(BaseModel):
    points: List[DeliveryPoint]
