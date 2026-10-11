import asyncio
import unittest

from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import JSONResponse

from main import app
from routelab.http_safety import MAX_BODY_BYTES, RequestSafety
from routelab.importers import import_file

ORIGIN = "https://routes.example.com"


async def request(body=b"{}", content_type=b"application/json", extra_headers=()):
    messages = []
    delivered = False

    async def endpoint(scope, receive, send):
        received = await receive()
        await JSONResponse({"bytes": len(received["body"])})(scope, receive, send)

    async def receive():
        nonlocal delivered
        if delivered:
            return {"type": "http.disconnect"}
        delivered = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        messages.append(message)

    guarded = CORSMiddleware(
        TrustedHostMiddleware(
            RequestSafety(endpoint, allowed_origins=[ORIGIN]), allowed_hosts=["api.example.com"]
        ),
        allow_origins=[ORIGIN],
        allow_methods=["GET", "POST"],
    )
    await guarded(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/runs",
            "headers": list(
                {
                    b"host": b"api.example.com",
                    b"origin": ORIGIN.encode(),
                    b"content-type": content_type,
                    **dict(extra_headers),
                }.items()
            ),
        },
        receive,
        send,
    )
    return messages


class RequestSafetyTests(unittest.TestCase):
    def test_production_cors_wraps_request_and_host_guards(self):
        self.assertEqual(
            [middleware.cls for middleware in app.user_middleware],
            [CORSMiddleware, TrustedHostMiddleware, RequestSafety],
        )

    def test_allowed_origin_can_read_guard_errors(self):
        cases = [
            ({"extra_headers": [(b"content-length", b"invalid")]}, 400),
            ({"extra_headers": [(b"content-length", str(MAX_BODY_BYTES + 1).encode())]}, 413),
            ({"extra_headers": [(b"host", b"wrong.example.com")]}, 400),
            ({"body": b'{"value": NaN}'}, 400),
        ]
        for kwargs, expected_status in cases:
            with self.subTest(kwargs=kwargs):
                response = asyncio.run(request(**kwargs))[0]
                self.assertEqual(response["status"], expected_status)
                self.assertEqual(
                    dict(response["headers"])[b"access-control-allow-origin"], ORIGIN.encode()
                )

    def test_json_media_types_reject_nonstandard_numbers_and_deep_nesting(self):
        for content_type in (
            b"application/json",
            b"application/json; charset=utf-8",
            b"application/problem+json",
            b"APPLICATION/JSON",
        ):
            for body in (b'{"value": Infinity}', b"[" * 2000 + b"0" + b"]" * 2000):
                with self.subTest(content_type=content_type, body_length=len(body)):
                    self.assertEqual(
                        asyncio.run(request(body=body, content_type=content_type))[0]["status"],
                        400,
                    )

    def test_valid_json_body_reaches_endpoint_unchanged(self):
        body = b'{"name": "A route", "nested": [{"value": 1}]}'
        messages = asyncio.run(request(body=body, content_type=b"application/vnd.routelab+json"))
        self.assertEqual(messages[0]["status"], 200)
        self.assertIn(str(len(body)).encode(), messages[1]["body"])

    def test_deep_import_json_returns_validation_error(self):
        with self.assertRaisesRegex(ValueError, "nested too deeply"):
            import_file("scenario.json", b"[" * 2000 + b"0" + b"]" * 2000)
