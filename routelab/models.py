"""Public contracts. Distances are kilometres; all schedule values are minutes."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Stop(Model):
    id: str = Field(min_length=1, max_length=80)
    name: str = Field(default="", max_length=120)
    x: float = Field(default=0, ge=-10000, le=10000)
    y: float = Field(default=0, ge=-10000, le=10000)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    demand: float = Field(default=1, ge=0, le=100000)
    service_minutes: float = Field(default=5, ge=0, le=1440)
    window_start: float = Field(default=0, ge=0, le=10080)
    window_end: float = Field(default=480, ge=0, le=10080)

    @model_validator(mode="after")
    def ordered_window(self):
        if self.window_end < self.window_start:
            raise ValueError("Window end must be at or after its start")
        return self


class Fleet(Model):
    count: int = Field(default=4, ge=1, le=25)
    capacity: float = Field(default=30, gt=0, le=100000)
    start_time: float = Field(default=0, ge=0, le=10080)
    end_time: float = Field(default=480, ge=0, le=10080)
    max_distance_km: float | None = Field(default=None, gt=0, le=100000)

    @model_validator(mode="after")
    def ordered_shift(self):
        if self.end_time <= self.start_time:
            raise ValueError("Shift end must be later than its start")
        return self


class RoadSnapshot(Model):
    engine: str = Field(pattern=r"^[a-f0-9]{64}$")
    coordinates_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    captured_at: str = Field(max_length=40)
    snapped: list[
        tuple[Annotated[float, Field(ge=-180, le=180)], Annotated[float, Field(ge=-90, le=90)]]
    ] = Field(max_length=101)
    hints: list[Annotated[str, Field(max_length=4096)]] = Field(max_length=101)


class MatrixInput(Model):
    distances_km: list[Annotated[list[float | None], Field(max_length=101)]] = Field(max_length=101)
    durations_minutes: list[Annotated[list[float | None], Field(max_length=101)]] = Field(
        max_length=101
    )
    source: str = Field(default="imported snapshot", max_length=160)
    profile: str = Field(default="driving", max_length=80)
    data_version: str = Field(default="unspecified", max_length=120)
    road: RoadSnapshot | None = None


class VehicleExecution(Model):
    vehicle_index: int = Field(ge=0, le=24)
    completed: list[str] = Field(default_factory=list, max_length=100)
    assigned: list[str] = Field(max_length=100)
    ready_time: float = Field(ge=0, le=20000)


class Scenario(Model):
    name: str = Field(default="Untitled scenario", min_length=1, max_length=120)
    description: str = Field(default="", max_length=1500)
    coordinate_mode: Literal["cartesian", "geographic"] = "cartesian"
    nodes: list[Stop] = Field(min_length=2, max_length=101)
    depot_id: str = "depot"
    fleet: Fleet = Field(default_factory=Fleet)
    speed_kph: float = Field(default=30, ge=0.01, le=200)
    travel_model: Literal["straight_line", "road"] = "straight_line"
    matrix: MatrixInput | None = None
    execution: list[VehicleExecution] = Field(default_factory=list, max_length=25)

    @model_validator(mode="after")
    def consistent(self):
        ids = [node.id for node in self.nodes]
        if len(set(ids)) != len(ids):
            raise ValueError("Every node needs a unique ID")
        if self.depot_id not in ids:
            raise ValueError("The depot must reference a node")
        depot = next(n for n in self.nodes if n.id == self.depot_id)
        if depot.demand != 0 or depot.service_minutes != 0:
            raise ValueError("Depot demand and service duration must be zero")
        if self.coordinate_mode == "geographic" and any(
            n.latitude is None or n.longitude is None for n in self.nodes
        ):
            raise ValueError("Geographic nodes require latitude and longitude")
        if self.matrix:
            size = len(ids)
            if self.matrix.road and (
                len(self.matrix.road.snapped) != size or len(self.matrix.road.hints) != size
            ):
                raise ValueError("Road snapshot locations and hints must match the node order")
            for table in (self.matrix.distances_km, self.matrix.durations_minutes):
                if len(table) != size or any(len(row) != size for row in table):
                    raise ValueError("Matrix dimensions must match the node order")
                if any(
                    v is not None and (v < 0 or v != v or v > 1e9) for row in table for v in row
                ):
                    raise ValueError(
                        "Matrix entries must be finite values between 0 and 1e9, or null"
                    )
                if any(table[i][i] != 0 for i in range(size)):
                    raise ValueError("Matrix diagonal entries must be zero")
            for i in range(size):
                for j in range(size):
                    if (self.matrix.distances_km[i][j] is None) != (
                        self.matrix.durations_minutes[i][j] is None
                    ):
                        raise ValueError("Distance and duration reachability must agree")
        if self.execution:
            seen_vehicles, assigned = set(), []
            for state in self.execution:
                if state.vehicle_index >= self.fleet.count or state.vehicle_index in seen_vehicles:
                    raise ValueError(
                        "Execution states must have distinct available vehicle indices"
                    )
                seen_vehicles.add(state.vehicle_index)
                if not set(state.completed).issubset(state.assigned) or len(
                    set(state.completed)
                ) != len(state.completed):
                    raise ValueError("Completed stops must be distinct assigned customers")
                assigned.extend(state.assigned)
            if len(set(assigned)) != len(assigned) or set(assigned) != set(ids) - {self.depot_id}:
                raise ValueError("Execution assignments must cover every customer exactly once")
        return self


Algorithm = Literal["greedy", "local_search", "alns", "exact", "ortools"]


class RunOptions(Model):
    algorithm: Algorithm = "alns"
    seed: int = Field(default=42, ge=0, le=2147483647)
    time_limit_seconds: float = Field(default=3, ge=0.05, le=30)
    iterations: int = Field(default=600, ge=1, le=10000)
    removal_fraction: float = Field(default=0.25, ge=0.05, le=0.6)
    adaptive: bool = True
    local_improvement: bool = True


class RunRequest(Model):
    scenario: Scenario
    options: RunOptions = Field(default_factory=RunOptions)


class ExperimentRequest(Model):
    scenario: Scenario
    algorithms: list[Algorithm] = Field(
        default=["greedy", "local_search", "alns"], min_length=1, max_length=5
    )
    seeds: list[int] = Field(default=[11, 22, 33], min_length=1, max_length=10)
    time_limit_seconds: float = Field(default=2, ge=0.05, le=10)
    iterations: int = Field(default=400, ge=1, le=10000)
    removal_fraction: float = Field(default=0.25, ge=0.05, le=0.6)
    adaptive: bool = True
    local_improvement: bool = True

    @model_validator(mode="after")
    def bounded(self):
        if len(set(self.algorithms)) != len(self.algorithms) or len(set(self.seeds)) != len(
            self.seeds
        ):
            raise ValueError("Algorithms and seeds must be unique")
        if any(seed < 0 or seed > 2147483647 for seed in self.seeds):
            raise ValueError("Seeds must be nonnegative 32-bit integers")
        if len(self.algorithms) * len(self.seeds) * self.time_limit_seconds > 120:
            raise ValueError("An interactive experiment may request at most 120 solver-seconds")
        return self


class ReplanRequest(Model):
    parent_job_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    vehicle_index: int = Field(default=0, ge=0, le=24)
    completed_stops: int = Field(default=1, ge=0, le=100)
    delay_minutes: float = Field(default=20, ge=0, le=480)
    change_budget: int | None = Field(default=None, ge=0, le=101)
    options: RunOptions = Field(default_factory=RunOptions)
