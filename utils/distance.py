import math
from typing import List, Literal

def euclidean_distance(x1: float, y1: float, x2: float, y2: float) -> float:
    return math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    phi1, phi2 = (math.radians(lat1), math.radians(lat2))
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def build_distance_matrix(points: List[dict], mode: Literal['euclidean', 'haversine']='haversine') -> List[List[float]]:
    n = len(points)
    matrix: List[List[float]] = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            if mode == 'haversine':
                d = haversine_distance(points[i]['latitude'], points[i]['longitude'], points[j]['latitude'], points[j]['longitude'])
            else:
                d = euclidean_distance(points[i]['x'], points[i]['y'], points[j]['x'], points[j]['y'])
            matrix[i][j] = d
            matrix[j][i] = d
    return matrix