import json
import math
import os
from urllib.error import URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from . import store
from .matrices import digest


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def service_url(value, public_host, local_name):
    url = urlsplit(value)
    local = url.hostname in ("localhost", "127.0.0.1", "::1", local_name)
    public = url.hostname == public_host and url.scheme == "https" and url.port in (None, 443)
    if not (local and url.scheme in ("http", "https") or public) or any(
        (url.username, url.password, url.path, url.query, url.fragment)
    ):
        raise ValueError(f"Use the HTTPS community service or a loopback/{local_name} service URL")
    return value


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
        if len(raw) > limit:
            raise ValueError("Geographic service response is too large")
        return json.loads(raw)
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise ValueError(
            "Geographic service is unavailable. Retry, or configure a local service."
        ) from exc


def photon_url():
    return service_url(
        os.environ.get("ROUTELAB_PHOTON_URL", "https://photon.komoot.io").rstrip("/"),
        "photon.komoot.io",
        "photon",
    )


def search(query):
    base = photon_url()
    query = " ".join(query.split())
    if not 2 <= len(query) <= 160:
        raise ValueError("Enter 2–160 characters to search for a place")
    key = digest({"service": base, "query": query.casefold(), "kind": "places-v1"})
    cached = store.geo_cached(key)
    if cached is not None:
        return cached
    body = fetch_json(
        base, "/api/?" + urlencode({"q": query, "limit": 6, "lang": "en"}), 512 * 1024
    )
    results = []
    try:
        for item in body["features"][:6]:
            lon, lat = item["geometry"]["coordinates"][:2]
            if not all(
                isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
                for v in (lon, lat)
            ) or not (-180 <= lon <= 180 and -85 <= lat <= 85):
                continue
            props = item["properties"]
            label = ", ".join(
                dict.fromkeys(
                    str(props[k])
                    for k in ("name", "street", "city", "state", "country")
                    if props.get(k)
                )
            )[:300]
            place = {"name": label or query, "latitude": lat, "longitude": lon}
            if place not in results:
                results.append(place)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Place search returned invalid data") from exc
    store.cache_geo(key, results, 7 * 86400)
    return results


def map_configuration():
    template = (
        os.environ.get("ROUTELAB_TILE_URL") or "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
    )
    url = urlsplit(template)
    if (
        url.scheme not in ("http", "https")
        or url.username
        or url.password
        or any(x not in template for x in ("{z}", "{x}", "{y}"))
    ):
        raise ValueError("ROUTELAB_TILE_URL must be an HTTP(S) tile template with {z}, {x}, {y}")
    if url.scheme == "http" and url.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError("Remote map tiles require HTTPS")
    return {
        "tile_url": template,
        "search_provider": "Photon",
        "search_public": photon_url() == "https://photon.komoot.io",
    }
