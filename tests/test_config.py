import asyncio
import os
import unittest
from unittest.mock import patch

from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import JSONResponse

from config import get_allowed_hosts, get_cors_origins
from routelab.http_safety import RequestSafety


class AllowedHostTests(unittest.TestCase):
    def test_local_defaults_without_render(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(get_allowed_hosts(), ["localhost", "127.0.0.1"])

    def test_render_hostname_accepts_health_check_with_netlify_cors(self):
        hostname = "delivery-backend-22c4.onrender.com"
        origin = "https://droptimizer.netlify.app"
        with patch.dict(
            os.environ,
            {"RENDER_EXTERNAL_HOSTNAME": hostname, "APP_CORS_ORIGINS": f'["{origin}"]'},
            clear=True,
        ):
            allowed_hosts = get_allowed_hosts()
            allowed_origins = get_cors_origins()
        self.assertEqual(allowed_hosts, ["localhost", "127.0.0.1", hostname])

        async def health(scope, receive, send):
            await JSONResponse({"status": "ok"})(scope, receive, send)

        app = RequestSafety(health, allowed_origins=allowed_origins)
        app = TrustedHostMiddleware(app, allowed_hosts=allowed_hosts)
        app = CORSMiddleware(
            app,
            allow_origins=allowed_origins,
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type", "Idempotency-Key"],
        )

        async def request(host):
            messages = []

            async def receive():
                return {"type": "http.request", "body": b"", "more_body": False}

            async def send(message):
                messages.append(message)

            await app(
                {
                    "type": "http",
                    "method": "GET",
                    "path": "/health",
                    "headers": [(b"host", host.encode()), (b"origin", origin.encode())],
                },
                receive,
                send,
            )
            return messages[0]

        response = asyncio.run(request(hostname))
        self.assertEqual(response["status"], 200)
        self.assertEqual(dict(response["headers"])[b"access-control-allow-origin"], origin.encode())
        self.assertEqual(asyncio.run(request("other-service.onrender.com"))["status"], 400)

    def test_explicit_hosts_override_render_and_local_defaults(self):
        with patch.dict(
            os.environ,
            {
                "RENDER_EXTERNAL_HOSTNAME": "delivery-backend-22c4.onrender.com",
                "ROUTELAB_ALLOWED_HOSTS": " api.example.com , localhost , ",
            },
            clear=True,
        ):
            self.assertEqual(get_allowed_hosts(), ["api.example.com", "localhost"])

    def test_explicit_empty_override_remains_empty(self):
        with patch.dict(
            os.environ,
            {
                "RENDER_EXTERNAL_HOSTNAME": "delivery-backend-22c4.onrender.com",
                "ROUTELAB_ALLOWED_HOSTS": "",
            },
            clear=True,
        ):
            self.assertEqual(get_allowed_hosts(), [])
