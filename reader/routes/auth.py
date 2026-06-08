"""Authentication routes: login and logout."""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from server.config import get_config
from .. import auth as reader_auth
from ._common import templates, _reader_auth_enabled

router = APIRouter(tags=["reader"])


@router.get("/login", include_in_schema=False)
def reader_login_get(request: Request, next: str = ""):
    """Login page; redirect to library if already authenticated or auth disabled."""
    if not _reader_auth_enabled():
        return RedirectResponse(url=request.url_for("browse_root"), status_code=302)
    cookie = request.cookies.get(reader_auth.SESSION_COOKIE_NAME)
    config = get_config()
    if reader_auth.verify_session_cookie(cookie, config.reader_auth.password):
        target = next.strip() or request.url_for("browse_root")
        return RedirectResponse(url=target, status_code=302)
    return _login_template(request, next=next or "")


@router.post("/login", include_in_schema=False)
def reader_login_post(
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
    next: str = Form(""),
):
    """Validate credentials and set session cookie on success."""
    config = get_config()
    if not config.reader_auth.enabled:
        return RedirectResponse(url=request.url_for("browse_root"), status_code=302)
    if username != config.reader_auth.user or password != config.reader_auth.password:
        return _login_template(request, error="Invalid username or password.", next=next)
    cookie_value = reader_auth.create_session_cookie_value(
        config.reader_auth.user, config.reader_auth.password
    )
    next_path = next.strip()
    if next_path.startswith("/reader"):
        target = next_path
    else:
        target = request.url_for("browse_root")
    response = RedirectResponse(url=target, status_code=302)
    response.set_cookie(
        key=reader_auth.SESSION_COOKIE_NAME,
        value=cookie_value,
        max_age=reader_auth.SESSION_MAX_AGE_SECONDS,
        path="/reader",
        httponly=True,
        samesite="lax",
    )
    return response


def _login_template(request: Request, error: str | None = None, next: str = ""):
    try:
        title = get_config().library.name
    except FileNotFoundError:
        title = "Comic Library"
    return templates.TemplateResponse(
        request,
        "login.html",
        {"title": title, "error": error, "next": next},
    )


@router.post("/logout", include_in_schema=False)
def reader_logout(request: Request):
    """Clear session cookie and redirect to login."""
    response = RedirectResponse(url=request.url_for("reader_login_get"), status_code=302)
    response.delete_cookie(
        key=reader_auth.SESSION_COOKIE_NAME,
        path="/reader",
    )
    return response
