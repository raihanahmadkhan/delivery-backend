

import csv
import io
from typing import List


def parse_csv(content: bytes) -> List[dict]:
    
    text = content.decode("utf-8-sig")   
    reader = csv.DictReader(io.StringIO(text))

    
    if reader.fieldnames is None:
        raise ValueError("CSV file appears to be empty.")

    
    normalised_fields = [f.strip().lower() for f in reader.fieldnames]

    required = {"latitude", "longitude"}
    missing = required - set(normalised_fields)
    if missing:
        raise ValueError(
            f"CSV is missing required columns: {missing}. "
            f"Found: {reader.fieldnames}"
        )

    points: List[dict] = []

    for row_num, row in enumerate(reader, start=2):   
        
        norm_row = {k.strip().lower(): v.strip() for k, v in row.items() if k}

        try:
            lat = float(norm_row["latitude"])
            lon = float(norm_row["longitude"])
        except (ValueError, KeyError) as exc:
            raise ValueError(
                f"Row {row_num}: invalid coordinate values - {exc}"
            ) from exc

        
        if not (-90 <= lat <= 90):
            raise ValueError(f"Row {row_num}: latitude {lat} is out of range [-90, 90].")
        if not (-180 <= lon <= 180):
            raise ValueError(f"Row {row_num}: longitude {lon} is out of range [-180, 180].")

        point = {
            "id":         int(norm_row.get("id", row_num - 2)),
            "name":       norm_row.get("name", f"Node {row_num - 2}"),
            "latitude":   lat,
            "longitude":  lon,
            "demand":     float(norm_row.get("demand", 0) or 0),
            "time_window_start": float(norm_row.get("time_window_start", 0) or 0),
            "time_window_end":   float(norm_row.get("time_window_end", 1440) or 1440),
        }
        points.append(point)

    if not points:
        raise ValueError("CSV file contains no data rows.")

    return points
