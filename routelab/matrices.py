import hashlib
import json
import math
from dataclasses import dataclass

from .models import Scenario


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def coordinates_hash(scenario: Scenario) -> str:
    return digest([[n.id, n.longitude, n.latitude] for n in scenario.nodes])


@dataclass
class Matrix:
    ids: list[str]
    distances: list[list[float | None]]
    durations: list[list[float | None]]
    provenance: dict
    hash: str

    def __post_init__(self):
        self.index = {node_id: i for i, node_id in enumerate(self.ids)}

    def edge(self, source: str, target: str):
        i, j = self.index[source], self.index[target]
        return self.distances[i][j], self.durations[i][j]


def build_matrix(scenario: Scenario) -> Matrix:
    if scenario.travel_model == "road" and scenario.matrix is None:
        raise ValueError("Build a road matrix before solving this geographic scenario")
    ids = [node.id for node in scenario.nodes]
    if scenario.matrix:
        supplied = scenario.matrix
        distances, durations = supplied.distances_km, supplied.durations_minutes
        provenance = {
            "kind": "imported",
            "source": supplied.source,
            "profile": supplied.profile,
            "data_version": supplied.data_version,
        }
        if supplied.road:
            if (
                scenario.coordinate_mode != "geographic"
                or supplied.road.coordinates_hash != coordinates_hash(scenario)
            ):
                raise ValueError(
                    "Locations changed after the road snapshot. Rebuild the road matrix."
                )
            provenance["kind"] = "road"
            provenance["road"] = supplied.road.model_dump()
    else:
        distances = []
        for a in scenario.nodes:
            row = []
            for b in scenario.nodes:
                if scenario.coordinate_mode == "cartesian":
                    distance = math.hypot(a.x - b.x, a.y - b.y)
                else:
                    lat1, lat2 = math.radians(a.latitude), math.radians(b.latitude)
                    dlat = lat2 - lat1
                    dlon = math.radians(b.longitude - a.longitude)
                    h = (
                        math.sin(dlat / 2) ** 2
                        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
                    )
                    distance = 6371 * 2 * math.asin(math.sqrt(min(1, max(0, h))))
                row.append(distance)
            distances.append(row)
        durations = [[distance / scenario.speed_kph * 60 for distance in row] for row in distances]
        provenance = {
            "kind": "euclidean" if scenario.coordinate_mode == "cartesian" else "haversine",
            "source": "synthetic straight-line model",
            "speed_kph": scenario.speed_kph,
            "profile": "constant speed; not road routing",
        }
    payload = {
        "ids": ids,
        "distances_km": distances,
        "durations_minutes": durations,
        "provenance": provenance,
    }
    return Matrix(ids, distances, durations, provenance, digest(payload))
