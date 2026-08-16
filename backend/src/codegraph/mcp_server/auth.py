"""Bearer-token ASGI middleware for the MCP server (slice 09)."""

from __future__ import annotations

import hmac
import json

_EXEMPT_PATHS = frozenset({"/healthz"})


class BearerAuthMiddleware:
    """Rejects any HTTP request without the expected bearer token.

    Pure ASGI: runs before any MCP handling. /healthz is the only exempt
    route (compose healthcheck). Non-HTTP scopes (lifespan) pass through.
    """

    def __init__(self, app, token: str):
        if not token:
            raise RuntimeError(
                "MCP_BEARER_TOKEN is not set — refusing to start the MCP "
                "server without authentication. Set it in .env."
            )
        self.app = app
        self._expected = f"Bearer {token}".encode()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] in _EXEMPT_PATHS:
            await self.app(scope, receive, send)
            return
        provided = next(
            (value for name, value in scope.get("headers", []) if name == b"authorization"),
            b"",
        )
        if not hmac.compare_digest(provided, self._expected):
            body = json.dumps({"error": "unauthorized"}).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode()),
                        (b"www-authenticate", b"Bearer"),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        await self.app(scope, receive, send)
