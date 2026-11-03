"""Keep the local API behind its configured Host and browser-origin boundary."""

from __future__ import annotations

from urllib.parse import urlsplit

from starlette.requests import Request
from starlette.responses import JSONResponse

from services.api.app.errors import reason
from services.common.config import get_settings


class LocalAccessMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        settings = get_settings()
        hosts = request.headers.getlist("host")
        try:
            host = urlsplit("//" + hosts[0]) if len(hosts) == 1 else None
            valid_host = (
                host is not None
                and host.hostname in settings.api_allowed_hosts
                and host.username is None and host.password is None
                and not host.path and not host.query and not host.fragment
                and host.port != 0
            )
        except ValueError:
            valid_host = False

        if not valid_host:
            response = JSONResponse(
                {"detail": reason("invalid_host", "Host is outside the local API allowlist")},
                status_code=403,
            )
            await response(scope, receive, send)
            return

        # Non-browser clients (CLI, Worker, health checks) send no Origin.
        # Browsers supply one for cross-origin reads and state-changing calls.
        # Do not trust X-Forwarded-Host: nginx preserves the local Host itself.
        origins = request.headers.getlist("origin")
        same_origin = f"{scope.get('scheme', 'http')}://{hosts[0]}"
        allowed = settings.api_allowed_origins + [same_origin]
        if (
            (origins and (len(origins) != 1 or origins[0] not in allowed))
            or request.headers.get("sec-fetch-site") == "cross-site"
            or (
                request.method not in {"GET", "HEAD", "OPTIONS"}
                and request.headers.get("content-type", "").split(";", 1)[0].strip()
                in {"application/x-www-form-urlencoded", "multipart/form-data", "text/plain"}
            )
        ):
            response = JSONResponse(
                {"detail": reason("origin_not_allowed", "Request origin is not authorized")},
                status_code=403,
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
