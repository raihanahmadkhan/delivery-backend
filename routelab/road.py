"""OSRM matrices and geometry. Never substitute straight-line travel on failure."""

import math
import os
from datetime import UTC, datetime
from urllib.parse import urlencode

from . import store
from .geography import bounded_coordinate, fetch_json, service_url
from .matrices import coordinates_hash, digest
from .models import MatrixInput, Scenario

PUBLIC_ENGINE = "https://router.project-osrm.org"


def configuration():
    base = service_url(
        os.environ.get("ROUTELAB_OSRM_URL", PUBLIC_ENGINE).rstrip("/"),
        "router.project-osrm.org",
        "osrm",
    )
    public = base == PUBLIC_ENGINE
    version = os.environ.get("ROUTELAB_OSRM_DATA_VERSION", "").strip()
    if not version and not public:
        raise ValueError("Set ROUTELAB_OSRM_DATA_VERSION to your road extract/profile version")
    if len(version) > 120:
        raise ValueError("Road data version must be at most 120 characters")
    return base, version or "community-unversioned"


def configured():
    try:
        configuration()
        return True
    except ValueError:
        return False


def valid_point(lon, lat):
    return bounded_coordinate(lon, -180, 180) and bounded_coordinate(lat, -90, 90)


def valid_metric(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return value >= 0 and math.isfinite(value)
    except OverflowError:
        return False


def scaled_matrix(values, size, divisor):
    if not isinstance(values, list) or len(values) != size:
        raise ValueError("Road engine returned an invalid matrix")
    output = []
    for row in values:
        if not isinstance(row, list) or len(row) != size:
            raise ValueError("Road engine returned an invalid matrix")
        if any(value is not None and not valid_metric(value) for value in row):
            raise ValueError("Road engine returned an invalid distance or duration")
        output.append([None if value is None else value / divisor for value in row])
    return output


def assert_ready(scenario):
    if scenario.travel_model == "road" and scenario.matrix is None:
        raise ValueError("Build a road matrix before starting a run")
    if (
        scenario.matrix
        and scenario.matrix.road
        and (
            scenario.coordinate_mode != "geographic"
            or scenario.matrix.road.coordinates_hash != coordinates_hash(scenario)
        )
    ):
        raise ValueError("Locations changed after the road snapshot. Rebuild the road matrix.")


def osrm(base, path):
    body = fetch_json(base, path)
    if not isinstance(body, dict) or body.get("code") != "Ok":
        code = body.get("code") if isinstance(body, dict) else None
        code = code[:120] if isinstance(code, str) else "invalid response"
        raise ValueError(
            f"Road engine: {code}. Place every stop within 200 m of a drivable road and within the installed region."
        )
    if body.get("fallback_speed_cells"):
        raise ValueError("Refusing straight-line fallback values from the road engine")
    return body


def snapshot(scenario: Scenario):
    if scenario.coordinate_mode != "geographic" or scenario.execution:
        raise ValueError("Road matrices require a static scenario with latitude and longitude")
    base, version = configuration()
    if base == PUBLIC_ENGINE and len(scenario.nodes) > 26:
        raise ValueError(
            "Community road routing supports at most 25 deliveries here. Self-host OSRM for up to 100."
        )
    coords = ";".join(f"{n.longitude:.7f},{n.latitude:.7f}" for n in scenario.nodes)
    day = datetime.now(UTC).date().isoformat() if base == PUBLIC_ENGINE else ""
    key = digest(
        {
            "kind": "road-v2",
            "base": base,
            "version": version,
            "coordinates": coordinates_hash(scenario),
            "day": day,
        }
    )
    cached = store.get_matrix_snapshot(key)
    if cached is None:
        body = osrm(
            base,
            f"/table/v1/driving/{coords}?"
            + urlencode(
                {
                    "annotations": "duration,distance",
                    "radiuses": ";".join(["200"] * len(scenario.nodes)),
                }
            ),
        )
        try:
            points = body["sources"]
            if not isinstance(points, list) or len(points) != len(scenario.nodes):
                raise ValueError("Road engine returned an incomplete snap list")
            snapped, hints = [], []
            for point in points:
                if (
                    not isinstance(point, dict)
                    or not isinstance(point.get("location"), list)
                    or len(point["location"]) != 2
                ):
                    raise ValueError("Invalid snapped road coordinate")
                lon, lat = point["location"]
                if not valid_point(lon, lat):
                    raise ValueError("Invalid snapped road coordinate")
                snapped.append([lon, lat])
                hint = point.get("hint", "")
                if not isinstance(hint, str) or len(hint) > 4096:
                    raise ValueError("Invalid road hint")
                hints.append(hint)
            cached = MatrixInput(
                distances_km=scaled_matrix(body["distances"], len(scenario.nodes), 1000),
                durations_minutes=scaled_matrix(body["durations"], len(scenario.nodes), 60),
                source="OSRM community / OpenStreetMap"
                if base == PUBLIC_ENGINE
                else "Self-hosted OSRM / OpenStreetMap",
                profile="driving / distances along fastest paths; no live traffic",
                data_version=version,
                road={
                    "engine": digest(base),
                    "coordinates_hash": coordinates_hash(scenario),
                    "captured_at": datetime.now(UTC).isoformat(),
                    "snapped": snapped,
                    "hints": hints,
                },
            ).model_dump()
            Scenario.model_validate({**scenario.model_dump(), "matrix": cached})
            store.save_matrix_snapshot(key, cached)
        except (KeyError, TypeError) as exc:
            raise ValueError("Road engine returned an invalid matrix") from exc
    return Scenario.model_validate(
        {**scenario.model_dump(), "matrix": cached, "travel_model": "road"}
    )


def geometry(scenario: Scenario, route: list[str]):
    assert_ready(scenario)
    if not scenario.matrix or not scenario.matrix.road:
        raise ValueError(
            "This matrix has no road geometry provenance. The map can show its stops only."
        )
    metadata = scenario.matrix.road
    ids = [n.id for n in scenario.nodes]
    if (
        not route
        or len(set(route)) != len(route)
        or any(n not in ids or n == scenario.depot_id for n in route)
    ):
        raise ValueError("Geometry requires distinct customer IDs from this scenario")
    indices = [ids.index(n) for n in [scenario.depot_id, *route, scenario.depot_id]]
    key = digest({"kind": "geometry-v1", "matrix": scenario.matrix.model_dump(), "route": route})
    cached = store.geo_cached(key)
    if cached is not None:
        return cached
    base, version = configuration()
    if metadata.engine != digest(base) or version != scenario.matrix.data_version:
        raise ValueError(
            "The road engine/version changed. Saved distances are intact; geometry is unavailable."
        )
    if len(metadata.hints) != len(ids) or len(metadata.snapped) != len(ids):
        raise ValueError("Incomplete road snapshot metadata")
    coords = ";".join(
        f"{scenario.nodes[i].longitude:.7f},{scenario.nodes[i].latitude:.7f}" for i in indices
    )
    body = osrm(
        base,
        f"/route/v1/driving/{coords}?"
        + urlencode(
            {
                "geometries": "geojson",
                "overview": "full",
                "steps": "false",
                "continue_straight": "false",
                "radiuses": ";".join(["200"] * len(indices)),
                "hints": ";".join(metadata.hints[i] for i in indices),
            }
        ),
    )
    try:
        result = body["routes"][0]
        legs = result["legs"]
        if not isinstance(legs, list) or len(legs) != len(indices) - 1:
            raise ValueError("Road geometry has the wrong number of legs")
        for leg, a, b in zip(legs, indices, indices[1:], strict=False):
            distance, duration = (
                scenario.matrix.distances_km[a][b],
                scenario.matrix.durations_minutes[a][b],
            )
            if (
                distance is None
                or duration is None
                or not valid_metric(leg["distance"])
                or not valid_metric(leg["duration"])
                or abs(leg["distance"] / 1000 - distance) > 0.01
                or abs(leg["duration"] / 60 - duration) > 1 / 60
            ):
                raise ValueError(
                    "Current road geometry no longer matches the saved matrix. Rebuild roads for a fresh run."
                )
        shape = result["geometry"]
        if (
            shape["type"] != "LineString"
            or not isinstance(shape["coordinates"], list)
            or not 2 <= len(shape["coordinates"]) <= 100000
        ):
            raise ValueError("Invalid road geometry")
        for point in shape["coordinates"]:
            if not isinstance(point, list) or len(point) != 2:
                raise ValueError("Invalid road geometry coordinate")
            lon, lat = point
            if not valid_point(lon, lat):
                raise ValueError("Invalid road geometry coordinate")
        output = {"geometry": shape, "matrix_hash": digest(scenario.matrix.model_dump())}
        store.cache_geo(key, output, 365 * 86400)
        return output
    except (KeyError, TypeError, IndexError) as exc:
        raise ValueError("Road engine returned malformed route geometry") from exc
