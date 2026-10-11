"""Enforce request limits before JSON/multipart parsing."""

import asyncio
import json

from starlette.responses import JSONResponse

MAX_BODY_BYTES = 3 * 1024 * 1024


def reject_json_constant(value):
    raise ValueError(f"Invalid JSON constant: {value}")


class RequestSafety:
    def __init__(self, app, allowed_origins):
        self.app = app
        self.allowed_origins = set(allowed_origins)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope["headers"])

        async def reject(status, detail):
            await JSONResponse({"detail": detail}, status)(scope, receive, send)

        if scope["method"] in ("POST", "PUT", "PATCH", "DELETE"):
            origin = headers.get(b"origin", b"").decode("latin1")
            if origin and origin not in self.allowed_origins:
                return await reject(403, "Untrusted request origin")
            content_length = headers.get(b"content-length")
            if content_length:
                try:
                    length = int(content_length)
                    if length < 0:
                        raise ValueError
                except ValueError:
                    return await reject(400, "Invalid Content-Length")
                if length > MAX_BODY_BYTES:
                    return await reject(413, "Request exceeds 3 MB")
            body = bytearray()
            try:
                async with asyncio.timeout(10):
                    while True:
                        message = await receive()
                        if message["type"] == "http.disconnect":
                            return
                        body.extend(message.get("body", b""))
                        if len(body) > MAX_BODY_BYTES:
                            return await reject(413, "Request exceeds 3 MB")
                        if not message.get("more_body", False):
                            break
            except TimeoutError:
                return await reject(408, "Request body timed out")
            content_type = headers.get(b"content-type", b"").split(b";", 1)[0].strip().lower()
            if content_type == b"application/json" or (
                content_type.startswith(b"application/") and content_type.endswith(b"+json")
            ):
                try:
                    json.loads(body, parse_constant=reject_json_constant)
                except (ValueError, RecursionError, UnicodeDecodeError):
                    return await reject(400, "Malformed JSON")
            pending = True
            upstream_receive = receive

            async def bounded_receive():
                nonlocal pending
                if pending:
                    pending = False
                    return {"type": "http.request", "body": bytes(body), "more_body": False}
                return await upstream_receive()

            receive = bounded_receive
        return await self.app(scope, receive, send)
