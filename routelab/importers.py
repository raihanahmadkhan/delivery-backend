import csv
import io
import json
import math
import re

from .models import Fleet, Scenario, Stop


def import_file(filename: str, content: bytes) -> Scenario:
    text = content.decode("utf-8-sig")
    if filename.lower().endswith(".json"):
        try:
            body = json.loads(text)
        except RecursionError as exc:
            raise ValueError("Scenario JSON is nested too deeply") from exc
        if not isinstance(body, dict):
            raise ValueError("Scenario JSON must be an object")
        return Scenario.model_validate(body.get("scenario", body))
    if filename.lower().endswith(".csv"):
        reader = csv.DictReader(io.StringIO(text))
        headers = [name.strip().lower() for name in (reader.fieldnames or [])]
        if not headers or any(not name for name in headers) or len(set(headers)) != len(headers):
            raise ValueError("CSV headers must be nonempty and unique")
        nodes = []
        geographic = False
        first_mode = None
        for index, raw in enumerate(reader):
            if None in raw or any(value is None for value in raw.values()):
                raise ValueError(f"Row {index + 2}: field count does not match the header")
            if index > 100:
                raise ValueError("At most 100 customers plus a depot are supported")
            row = {key.strip().lower(): (value or "").strip() for key, value in raw.items() if key}

            def number(key, default, row=row):
                return float(row.get(key) or default)

            has_latitude, has_longitude = bool(row.get("latitude")), bool(row.get("longitude"))
            if has_latitude != has_longitude:
                raise ValueError(f"Row {index + 2}: provide both latitude and longitude")
            geographic = has_latitude and has_longitude
            if first_mode is not None and first_mode != geographic:
                raise ValueError("All CSV rows must use the same coordinate system")
            first_mode = geographic
            if not geographic and not (row.get("x") and row.get("y")):
                raise ValueError(f"Row {index + 2}: provide x,y in km or latitude,longitude")
            nodes.append(
                Stop(
                    id=row.get("id") or ("depot" if index == 0 else f"s{index}"),
                    name=row.get("name") or ("Depot" if index == 0 else f"Stop {index}"),
                    x=number("x", 0),
                    y=number("y", 0),
                    latitude=number("latitude", 0) if geographic else None,
                    longitude=number("longitude", 0) if geographic else None,
                    demand=number("demand", 0 if index == 0 else 1),
                    service_minutes=number("service_minutes", 0 if index == 0 else 5),
                    window_start=number("window_start", row.get("time_window_start") or 0),
                    window_end=number("window_end", row.get("time_window_end") or 480),
                )
            )
        if not nodes:
            raise ValueError("CSV contains no stops")
        return Scenario(
            name=filename.rsplit(".", 1)[0],
            description="Imported CSV. Review fleet capacity and shift before solving.",
            nodes=nodes,
            depot_id=nodes[0].id,
            coordinate_mode="geographic" if geographic else "cartesian",
        )
    vehicle_count, capacity, records = None, None, []
    in_vehicles, in_customers = False, False
    for line in text.splitlines():
        upper = line.upper()
        if "VEHICLE" in upper:
            in_vehicles = True
        if "CUSTOMER" in upper:
            in_customers, in_vehicles = True, False
        fields = re.split(r"\s+", line.strip())
        try:
            values = [float(field) for field in fields]
        except ValueError:
            continue
        if in_vehicles and len(values) == 2:
            if not math.isfinite(values[0]) or not values[0].is_integer():
                raise ValueError("Vehicle count must be a finite integer")
            vehicle_count, capacity = int(values[0]), values[1]
        if in_customers and len(values) == 7:
            records.append(values)
    if not records or capacity is None:
        raise ValueError("Expected RouteLab JSON, coordinate CSV, or Solomon VRPTW text")
    if len(records) > 101:
        raise ValueError("Interactive import supports at most 100 customers")
    if vehicle_count > 25:
        raise ValueError(
            "This build supports at most 25 vehicles; do not silently alter a benchmark fleet"
        )
    if any(not math.isfinite(row[0]) or not row[0].is_integer() for row in records):
        raise ValueError("Solomon customer IDs must be finite integers")
    nodes = [
        Stop(
            id=str(int(row[0])),
            name="Depot" if index == 0 else f"Customer {int(row[0])}",
            x=row[1],
            y=row[2],
            demand=row[3],
            window_start=row[4],
            window_end=row[5],
            service_minutes=row[6],
        )
        for index, row in enumerate(records)
    ]
    return Scenario(
        name=filename.rsplit(".", 1)[0],
        description="Solomon convention: Euclidean distance and travel time numerically equal. Coordinates are benchmark units, displayed as km-equivalent; do not compare to geographic datasets.",
        nodes=nodes,
        depot_id=nodes[0].id,
        speed_kph=60,
        fleet=Fleet(count=vehicle_count, capacity=capacity, end_time=nodes[0].window_end),
    )
