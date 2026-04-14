import random
from typing import List


# Depot: New Delhi (central hub)
_DEPOT_LAT = 28.7041
_DEPOT_LON = 77.1025

# 50 major Indian cities with real coordinates
# (name, latitude, longitude)
_INDIAN_CITIES = [
    ("Mumbai",           19.0760,  72.8777),
    ("Bengaluru",        12.9716,  77.5946),
    ("Hyderabad",        17.3850,  78.4867),
    ("Ahmedabad",        23.0225,  72.5714),
    ("Chennai",          13.0827,  80.2707),
    ("Kolkata",          22.5726,  88.3639),
    ("Surat",            21.1702,  72.8311),
    ("Pune",             18.5204,  73.8567),
    ("Jaipur",           26.9124,  75.7873),
    ("Lucknow",          26.8467,  80.9462),
    ("Kanpur",           26.4499,  80.3319),
    ("Nagpur",           21.1458,  79.0882),
    ("Indore",           22.7196,  75.8577),
    ("Thane",            19.2183,  72.9781),
    ("Bhopal",           23.2599,  77.4126),
    ("Visakhapatnam",    17.6868,  83.2185),
    ("Patna",            25.5941,  85.1376),
    ("Vadodara",         22.3072,  73.1812),
    ("Ghaziabad",        28.6692,  77.4538),
    ("Ludhiana",         30.9010,  75.8573),
    ("Agra",             27.1767,  78.0081),
    ("Nashik",           19.9975,  73.7898),
    ("Faridabad",        28.4089,  77.3178),
    ("Meerut",           28.9845,  77.7064),
    ("Rajkot",           22.3039,  70.8022),
    ("Varanasi",         25.3176,  82.9739),
    ("Aurangabad",       19.8762,  75.3433),
    ("Dhanbad",          23.7957,  86.4304),
    ("Amritsar",         31.6340,  74.8723),
    ("Allahabad",        25.4358,  81.8463),
    ("Ranchi",           23.3441,  85.3096),
    ("Howrah",           22.5958,  88.2636),
    ("Coimbatore",       11.0168,  76.9558),
    ("Jabalpur",         23.1815,  79.9864),
    ("Gwalior",          26.2183,  78.1828),
    ("Vijayawada",       16.5062,  80.6480),
    ("Jodhpur",          26.2389,  73.0243),
    ("Madurai",           9.9252,  78.1198),
    ("Raipur",           21.2514,  81.6296),
    ("Kota",             25.2138,  75.8648),
    ("Chandigarh",       30.7333,  76.7794),
    ("Guwahati",         26.1445,  91.7362),
    ("Solapur",          17.6805,  75.9064),
    ("Hubli",            15.3647,  75.1240),
    ("Mysuru",           12.2958,  76.6394),
    ("Tiruchirappalli",  10.7905,  78.7047),
    ("Bareilly",         28.3670,  79.4304),
    ("Aligarh",          27.8974,  78.0880),
    ("Moradabad",        28.8386,  78.7733),
]

# 25 cities used for the 5×5 grid preset (labeled, placed at grid positions)
_GRID_CITY_NAMES = [
    "Jaipur",      "Agra",         "Lucknow",      "Varanasi",    "Patna",
    "Ahmedabad",   "Indore",       "Bhopal",        "Nagpur",      "Raipur",
    "Mumbai",      "Pune",         "Aurangabad",    "Hyderabad",   "Vijayawada",
    "Bengaluru",   "Mysuru",       "Coimbatore",    "Madurai",     "Chennai",
    "Kochi",       "Thiruvananthapuram", "Tiruchirappalli", "Visakhapatnam", "Hubli",
]


def _make_point(idx: int, lat: float, lon: float, name: str, demand: float = 10.0) -> dict:
    return {
        "id": idx,
        "name": name,
        "latitude": round(lat, 6),
        "longitude": round(lon, 6),
        "demand": demand,
        "time_window_start": 0.0,
        "time_window_end": 1440.0,
    }


def get_preset(name: str) -> List[dict]:
    presets = {
        "random20":  _random_points(n=20, seed=42),
        "random50":  _random_points(n=50, seed=99),
        "clustered": _clustered_points(),
        "grid":      _grid_points(),
    }

    if name not in presets:
        raise ValueError(
            f"Unknown preset '{name}'. Available: {list(presets.keys())}"
        )

    return presets[name]


def available_presets() -> List[str]:
    return ["random20", "random50", "clustered", "grid"]


def _random_points(n: int, seed: int) -> List[dict]:
    """Return depot + n delivery points using real major Indian city coordinates."""
    rng = random.Random(seed)

    # Shuffle a copy of the city list so selection is seeded but non-sequential
    cities = list(_INDIAN_CITIES)
    rng.shuffle(cities)

    # Take the first n cities (wrap around if n > available cities)
    selected = (cities * ((n // len(cities)) + 1))[:n]

    depot_name = "Depot - New Delhi"
    points = [_make_point(0, _DEPOT_LAT, _DEPOT_LON, depot_name, demand=0.0)]

    for i, (city_name, lat, lon) in enumerate(selected, start=1):
        demand = round(rng.uniform(5.0, 30.0), 1)
        points.append(_make_point(i, lat, lon, city_name, demand))

    return points


def _clustered_points() -> List[dict]:
    """
    Three regional clusters of Indian cities:
      Cluster 1 – North India  (Delhi / UP / Punjab belt)
      Cluster 2 – West India   (Maharashtra / Gujarat belt)
      Cluster 3 – South India  (Karnataka / Tamil Nadu / AP belt)
    """
    rng = random.Random(7)

    clusters = [
        # (cluster label, list of (city, lat, lon))
        (
            "North India",
            [
                ("Lucknow",    26.8467, 80.9462),
                ("Kanpur",     26.4499, 80.3319),
                ("Agra",       27.1767, 78.0081),
                ("Varanasi",   25.3176, 82.9739),
                ("Meerut",     28.9845, 77.7064),
                ("Ghaziabad",  28.6692, 77.4538),
                ("Allahabad",  25.4358, 81.8463),
                ("Bareilly",   28.3670, 79.4304),
            ],
        ),
        (
            "West India",
            [
                ("Mumbai",     19.0760, 72.8777),
                ("Pune",       18.5204, 73.8567),
                ("Nashik",     19.9975, 73.7898),
                ("Surat",      21.1702, 72.8311),
                ("Ahmedabad",  23.0225, 72.5714),
                ("Vadodara",   22.3072, 73.1812),
                ("Rajkot",     22.3039, 70.8022),
                ("Aurangabad", 19.8762, 75.3433),
            ],
        ),
        (
            "South India",
            [
                ("Bengaluru",       12.9716, 77.5946),
                ("Chennai",         13.0827, 80.2707),
                ("Hyderabad",       17.3850, 78.4867),
                ("Coimbatore",      11.0168, 76.9558),
                ("Madurai",          9.9252, 78.1198),
                ("Mysuru",          12.2958, 76.6394),
                ("Vijayawada",      16.5062, 80.6480),
                ("Visakhapatnam",   17.6868, 83.2185),
            ],
        ),
    ]

    points = [_make_point(0, _DEPOT_LAT, _DEPOT_LON, "Depot - New Delhi", demand=0.0)]
    idx = 1

    for cluster_label, city_list in clusters:
        # Pick 7–8 cities per cluster (seeded)
        sample_size = rng.randint(7, min(8, len(city_list)))
        sampled = rng.sample(city_list, sample_size)
        for city_name, lat, lon in sampled:
            demand = round(rng.uniform(8.0, 25.0), 1)
            points.append(_make_point(idx, lat, lon, city_name, demand))
            idx += 1

    return points


def _grid_points() -> List[dict]:
    """
    5×5 grid of evenly-spaced delivery points across central India,
    each labelled with the name of a major Indian city.
    """
    # Grid spans central India roughly between Mumbai and Patna
    lat_start = 12.00   # southern edge (near Bengaluru latitude)
    lon_start = 72.50   # western edge (near Mumbai longitude)

    lat_step = 3.80     # ~420 km north per row
    lon_step = 3.70     # ~370 km east per column

    points = [_make_point(0, _DEPOT_LAT, _DEPOT_LON, "Depot - New Delhi", demand=0.0)]
    idx = 1

    for row in range(5):
        for col in range(5):
            lat = lat_start + row * lat_step
            lon = lon_start + col * lon_step
            city_name = _GRID_CITY_NAMES[row * 5 + col]
            points.append(_make_point(idx, lat, lon, city_name, demand=10.0))
            idx += 1

    return points
