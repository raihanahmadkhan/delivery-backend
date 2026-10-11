import json
import os

_LOCALHOST_ORIGINS = [
    f"http://{host}:{port}" for host in ("localhost", "127.0.0.1") for port in (5173, 8080, 8000)
]


def get_cors_origins() -> list[str]:
    raw = os.environ.get("APP_CORS_ORIGINS", "").strip()
    if not raw:
        return _LOCALHOST_ORIGINS
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list) and all(isinstance(item, str) for item in parsed):
            return [item.strip().rstrip("/") for item in parsed if item.strip()]
    except (ValueError, TypeError):
        pass
    return [item.strip().rstrip("/") for item in raw.split(",") if item.strip()]


def get_allowed_hosts() -> list[str]:
    raw = os.environ.get("ROUTELAB_ALLOWED_HOSTS")
    if raw is not None:
        return [host.strip() for host in raw.split(",") if host.strip()]
    hosts = ["localhost", "127.0.0.1"]
    render_hostname = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "").strip()
    if render_hostname and render_hostname not in hosts:
        hosts.append(render_hostname)
    return hosts
