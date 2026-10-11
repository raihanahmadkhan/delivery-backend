import json
import os
from http.client import HTTPException
from urllib.error import URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from . import store
from .matrices import digest


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def service_url(value, public_host, local_name):
    try:
        url = urlsplit(value)
        port = url.port
    except ValueError as exc:
        raise ValueError("Geographic service URL has an invalid host or port") from exc
    local = url.hostname in ("localhost", "127.0.0.1", "::1", local_name)
    public = url.hostname == public_host and url.scheme == "https" and port in (None, 443)
    if not (local and url.scheme in ("http", "https") or public) or any(
        (url.username, url.password, url.path, url.query, url.fragment)
    ):
        raise ValueError(f"Use the HTTPS community service or a loopback/{local_name} service URL")
    host = f"[{url.hostname}]" if ":" in url.hostname else url.hostname
    if port is not None and port != (443 if url.scheme == "https" else 80):
        host = f"{host}:{port}"
    return f"{url.scheme}://{host}"


def fetch_json(base, path, limit=4 * 1024 * 1024):
    store.reserve_network_slot(base)
    req = Request(
        base + path,
        headers={
            "User-Agent": "RouteLab/1.0 (local routing workbench; https://github.com/raihanahmadkhan/delivery-backend)",
            "Accept": "application/json",
        },
    )
    try:
        with build_opener(ProxyHandler({}), NoRedirect()).open(req, timeout=15) as response:
            raw = response.read(limit + 1)
    except (URLError, TimeoutError, OSError, HTTPException) as exc:
        raise ValueError(
            "Geographic service is unavailable. Retry, or configure a local service."
        ) from exc
    if len(raw) > limit:
        raise ValueError("Geographic service response is too large")
    try:
        return json.loads(raw, parse_constant=reject_constant)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ValueError("Geographic service returned invalid JSON") from exc


def reject_constant(value):
    raise ValueError(f"Invalid JSON number: {value}")


def bounded_coordinate(value, lower, upper):
    return (
        isinstance(value, (int, float)) and not isinstance(value, bool) and lower <= value <= upper
    )


def search_label(properties, query):
    def text(key):
        value = properties.get(key, "")
        if (
            key in ("housenumber", "postcode")
            and isinstance(value, int)
            and not isinstance(value, bool)
        ):
            value = str(value)
        return " ".join(value.split())[:120] if isinstance(value, str) else ""

    address = " ".join(part for part in (text("housenumber"), text("street")) if part)
    parts = [text("name"), address]
    parts.extend(
        text(key)
        for key in ("locality", "district", "city", "county", "state", "postcode", "country")
    )
    seen = set()
    unique = []
    for part in parts:
        if part and part.casefold() not in seen:
            unique.append(part)
            seen.add(part.casefold())
    return ", ".join(unique)[:300] or query


def photon_url():
    return service_url(
        os.environ.get("ROUTELAB_PHOTON_URL", "https://photon.komoot.io").rstrip("/"),
        "photon.komoot.io",
        "photon",
    )


def search(query, latitude=None, longitude=None):
    if not isinstance(query, str):
        raise ValueError("Enter 2–160 characters to search for a place")
    query = " ".join(query.split())
    if not 2 <= len(query) <= 160:
        raise ValueError("Enter 2–160 characters to search for a place")
    if (latitude is None) != (longitude is None):
        raise ValueError("Provide both latitude and longitude for nearby search")
    focus = None
    if latitude is not None:
        if not bounded_coordinate(latitude, -85, 85) or not bounded_coordinate(
            longitude, -180, 180
        ):
            raise ValueError("Search focus must be finite latitude/longitude within the map bounds")
        # Nearby viewport movement should share results and provider request slots.
        focus = [round(latitude, 2) or 0.0, round(longitude, 2) or 0.0]
    base = photon_url()
    key = digest({"service": base, "query": query.casefold(), "focus": focus, "kind": "places-v2"})
    cached = store.geo_cached(key)
    if cached is not None:
        return cached
    params = {"q": query, "limit": 6, "lang": "en"}
    if focus is not None:
        params.update({"lat": focus[0], "lon": focus[1]})
    body = fetch_json(base, "/api/?" + urlencode(params), 512 * 1024)
    if not isinstance(body, dict) or not isinstance(body.get("features"), list):
        raise ValueError("Place search returned invalid data")
    features = body["features"][:6]
    results = []
    for item in features:
        if not isinstance(item, dict):
            continue
        geometry, properties = item.get("geometry"), item.get("properties")
        if not isinstance(geometry, dict) or not isinstance(properties, dict):
            continue
        coordinates = geometry.get("coordinates")
        if (
            geometry.get("type", "Point") != "Point"
            or not isinstance(coordinates, list)
            or len(coordinates) < 2
        ):
            continue
        lon, lat = coordinates[:2]
        if not bounded_coordinate(lon, -180, 180) or not bounded_coordinate(lat, -85, 85):
            continue
        place = {"name": search_label(properties, query), "latitude": lat, "longitude": lon}
        if place not in results:
            results.append(place)
    if features and not results:
        raise ValueError("Place search returned invalid data")
    store.cache_geo(key, results, 7 * 86400)
    return results


def map_configuration():
    template = (
        os.environ.get("ROUTELAB_TILE_URL") or "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
    )
    try:
        url = urlsplit(template)
        _ = url.port
    except ValueError as exc:
        raise ValueError("ROUTELAB_TILE_URL has an invalid host or port") from exc
    if (
        url.scheme not in ("http", "https")
        or not url.hostname
        or url.username
        or url.password
        or any(x not in template for x in ("{z}", "{x}", "{y}"))
    ):
        raise ValueError("ROUTELAB_TILE_URL must be an HTTP(S) tile template with {z}, {x}, {y}")
    if url.scheme == "http" and url.hostname not in ("localhost", "127.0.0.1"):
        raise ValueError("HTTP map tiles require localhost or 127.0.0.1; other hosts require HTTPS")
    return {
        "tile_url": template,
        "search_provider": "Photon",
        "search_public": photon_url() == "https://photon.komoot.io",
    }
