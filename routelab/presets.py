import math
import random

from .matrices import build_matrix
from .models import Fleet, Scenario, Stop

CATALOG = [
    {
        "id": "harbor",
        "name": "Harbor district",
        "description": "18 deliveries across three neighborhoods. A practical first experiment.",
        "customers": 18,
        "tag": "Start here",
    },
    {
        "id": "tight",
        "name": "The morning deadline",
        "description": "24 stops with windows constructed around a feasible witness schedule.",
        "customers": 24,
        "tag": "Time windows",
    },
    {
        "id": "scattered",
        "name": "Across the city",
        "description": "36 scattered customers. More opportunities for removal and repair.",
        "customers": 36,
        "tag": "Search depth",
    },
    {
        "id": "tiny",
        "name": "Six-stop proof",
        "description": "A small instance suitable for exhaustive optimality verification.",
        "customers": 6,
        "tag": "Exact reference",
    },
    {
        "id": "pune",
        "name": "Pune / synthetic stops",
        "description": "Geographic coordinates with a declared straight-line, constant-speed model.",
        "customers": 18,
        "tag": "Geography",
    },
]


def get_scenario(key: str) -> Scenario:
    item = next((item for item in CATALOG if item["id"] == key), None)
    if item is None:
        raise ValueError("Unknown scenario")
    rng = random.Random({"harbor": 17, "tight": 31, "scattered": 62, "tiny": 4, "pune": 17}[key])
    count = item["customers"]
    groups = math.ceil(count / 6)
    nodes = [Stop(id="depot", name="Distribution center", x=8, y=8, demand=0, service_minutes=0)]
    for index in range(count):
        group = index // 6
        angle = group * math.tau / groups
        if key == "scattered":
            x, y = rng.uniform(0.5, 15.5), rng.uniform(0.5, 15.5)
        else:
            x, y = (
                8 + math.cos(angle) * 4.5 + rng.uniform(-2.4, 2.4),
                8 + math.sin(angle) * 4.5 + rng.uniform(-2.4, 2.4),
            )
        nodes.append(
            Stop(
                id=f"s{index + 1}",
                name=f"Stop {index + 1:02d}",
                x=round(x, 3),
                y=round(y, 3),
                demand=rng.randint(2, 5),
                service_minutes=rng.choice([4, 5, 7]),
            )
        )
    scenario = Scenario(
        name=item["name"],
        description=item["description"],
        nodes=nodes,
        fleet=Fleet(count=groups, capacity=30),
    )
    if key == "tight":
        matrix = build_matrix(scenario)
        for group in range(groups):
            previous, clock = "depot", 0.0
            for node in nodes[1 + group * 6 : 1 + (group + 1) * 6]:
                _, travel = matrix.edge(previous, node.id)
                clock += travel
                node.window_start = max(0, round(clock - 8, 1))
                node.window_end = round(clock + 25, 1)
                clock += node.service_minutes
                previous = node.id
    if key == "pune":
        scenario.coordinate_mode = "geographic"
        for node in nodes:
            node.latitude = 18.5204 + (node.y - 8) / 111.32
            node.longitude = 73.8567 + (node.x - 8) / (111.32 * math.cos(math.radians(18.5204)))
    return Scenario.model_validate(scenario.model_dump())
