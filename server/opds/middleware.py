"""ASGI middleware for the Issued server."""

from __future__ import annotations

import logging
from urllib.parse import quote

from fastapi.responses import RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

from ..config import get_config
from reader import auth as reader_auth


class ReaderAuthMiddleware(BaseHTTPMiddleware):
    """Redirect to /reader/login when reader auth is enabled and session is invalid."""

    async def dispatch(self, request, call_next):
        path = request.url.path
        if not path.startswith("/reader"):
            return await call_next(request)
        if path.startswith("/reader/static"):
            return await call_next(request)
        if path == "/reader/login":
            return await call_next(request)
        if path == "/reader/logout" and request.method == "POST":
            return await call_next(request)
        try:
            config = get_config()
        except FileNotFoundError:
            return await call_next(request)
        if not config.reader_auth.enabled:
            return await call_next(request)
        cookie = request.cookies.get(reader_auth.SESSION_COOKIE_NAME)
        if reader_auth.verify_session_cookie(cookie, config.reader_auth.password):
            return await call_next(request)
        return RedirectResponse(
            url="/reader/login?next=" + quote(path),
            status_code=302,
        )


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log incoming requests with full URL for debugging."""

    async def dispatch(self, request, call_next):
        if not getattr(request.app.state, "logged_first_request", False):
            _logger = logging.getLogger("issued.request")
            user_agent = request.headers.get("user-agent", "")
            client_name = user_agent.split("/")[0] if user_agent else "unknown"
            client_ip = request.client.host if request.client else "unknown"
            message = (
                'client_connected="%s" ip="%s" url="%s %s" host="%s" ua="%s"'
                % (
                    client_name,
                    client_ip,
                    request.method,
                    str(request.url),
                    request.headers.get("host", ""),
                    user_agent,
                )
            )
            _logger.info(message)
            request.app.state.logged_first_request = True
        return await call_next(request)


class _ReaderAccessFilter(logging.Filter):
    """Filter out access log lines for successful requests to reduce console noise.
    Keep errors (4xx, 5xx) visible for debugging.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
            if any(
                pattern in msg
                for pattern in [
                    ' 200 OK',
                    '" 200',
                    ' 204 No Content',
                    '" 204',
                    ' 304 Not Modified',
                    '" 304',
                ]
            ):
                return False
            return True
        except Exception:
            return True


class _UvicornStartupFilter(logging.Filter):
    """Suppress all uvicorn startup messages; we print our own in lifespan."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        raw = str(getattr(record, "msg", ""))
        if "Started server process" in msg or "Started server process" in raw:
            return False
        if "Waiting for application startup" in msg or "Waiting for application startup" in raw:
            return False
        if "Application startup complete" in msg or "Application startup complete" in raw:
            return False
        if "running on" in msg or "running on" in raw:
            return False
        return True
