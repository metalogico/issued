"""FastAPI router for the web reader: browse library and read comics."""

from __future__ import annotations

import sys
from pathlib import Path
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from server.config import get_config
from server.database import db_connection

from . import auth as reader_auth
from . import repository as repo
from . import services


# Paths: support PyInstaller bundle (sys._MEIPASS) and normal run
if getattr(sys, "frozen", False):
    _base = Path(sys._MEIPASS) / "reader"
else:
    _base = Path(__file__).resolve().parent
TEMPLATES_DIR = _base / "templates"
STATIC_DIR = _base / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(tags=["reader"])


def _library_title() -> str:
    try:
        return get_config().library.name
    except FileNotFoundError:
        return "Comic Library"


def _reader_auth_enabled() -> bool:
    try:
        return get_config().reader_auth.enabled
    except FileNotFoundError:
        return False


# --- Login / Logout ---


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
        "login.html",
        {"request": request, "title": title, "error": error, "next": next},
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


# --- Browse: root ---


@router.get("", include_in_schema=False)
@router.get("/")
def browse_root(request: Request):
    """Browse root: first level (single folder contents or folder list + last added)."""
    with db_connection() as conn:
        top_folders = repo.get_top_folders(conn)

        if len(top_folders) == 1:
            folder_id = top_folders[0]["id"]
            subfolders = repo.get_subfolders_with_item_count(conn, folder_id)
            comics = repo.get_comics_in_folder(conn, folder_id)
            last_added_comics = repo.get_last_added_comics(conn, 24)
            continue_reading = repo.get_continue_reading_comics(conn, 12)
            return templates.TemplateResponse(
                "browser.html",
                {
                    "request": request,
                    "title": f"{top_folders[0]['name']} — {_library_title()}",
                    "breadcrumbs": [],
                    "folders": subfolders,
                    "comics": comics,
                    "show_last_added": True,
                    "last_added_comics": last_added_comics,
                    "continue_reading_comics": continue_reading,
                    "reader_auth_enabled": _reader_auth_enabled(),
                },
            )

        repo.add_folder_item_counts(conn, top_folders)
        last_added_comics = repo.get_last_added_comics(conn, 24)
        continue_reading = repo.get_continue_reading_comics(conn, 12)
        return templates.TemplateResponse(
            "browser.html",
            {
                "request": request,
                "title": _library_title(),
                "breadcrumbs": [],
                "folders": top_folders,
                "comics": [],
                "show_last_added": True,
                "last_added_comics": last_added_comics,
                "continue_reading_comics": continue_reading,
                "reader_auth_enabled": _reader_auth_enabled(),
            },
        )


# --- Browse: search ---


@router.get("/search")
def browse_search(request: Request, q: str = ""):
    """Search comics by filename or metadata."""
    with db_connection() as conn:
        comics = repo.search_comics(conn, q)

    return templates.TemplateResponse(
        "browser.html",
        {
            "request": request,
            "title": f"Search: {q} — {_library_title()}",
            "breadcrumbs": [],
            "folders": [],
            "comics": comics,
            "show_last_added": False,
            "last_added_comics": [],
            "continue_reading_comics": [],
            "reader_auth_enabled": _reader_auth_enabled(),
        },
    )


# --- Browse: last added ---


@router.get("/recent")
@router.get("/last-added")
def browse_last_added(request: Request, limit: int = 50):
    """Browse last added comics."""
    with db_connection() as conn:
        comics = repo.get_last_added_comics(conn, min(limit, 200))

    return templates.TemplateResponse(
        "browser.html",
        {
            "request": request,
            "title": f"Last added — {_library_title()}",
            "breadcrumbs": [],
            "folders": [],
            "comics": comics,
            "show_last_added": False,
            "last_added_comics": [],
            "continue_reading_comics": [],
            "reader_auth_enabled": _reader_auth_enabled(),
        },
    )


# --- Browse: folder ---


@router.get("/folder/{folder_id:int}")
def browse_folder(request: Request, folder_id: int):
    """Browse a folder: subfolders and comics."""
    with db_connection() as conn:
        folder = repo.get_folder(conn, folder_id)
        if not folder:
            raise HTTPException(status_code=404, detail="Folder not found")

        subfolders = repo.get_subfolders_with_item_count(conn, folder_id)
        comics = repo.get_comics_in_folder(conn, folder_id)
        breadcrumbs = repo.get_breadcrumbs_for_folder(conn, folder_id)

    return templates.TemplateResponse(
        "browser.html",
        {
            "request": request,
            "title": f"{folder['name']} — {_library_title()}",
            "breadcrumbs": breadcrumbs,
            "folders": subfolders,
            "comics": comics,
            "show_last_added": False,
            "last_added_comics": [],
            "continue_reading_comics": [],
            "reader_auth_enabled": _reader_auth_enabled(),
        },
    )


# --- Reader: single comic view ---


@router.get("/comic/{comic_uuid}")
def reader_view(request: Request, comic_uuid: str):
    """Reader page: open a comic and flip through pages."""
    comic = services.get_comic_by_uuid(comic_uuid)
    if not comic:
        raise HTTPException(status_code=404, detail="Comic not found")

    page_count = comic["page_count"] or 1
    with db_connection() as conn:
        initial_page = repo.get_initial_page(conn, comic_uuid, page_count)
        folder_id = repo.get_folder_id_for_comic(conn, comic_uuid)
        breadcrumbs = repo.get_breadcrumbs_for_folder(conn, folder_id) if folder_id else []

    return templates.TemplateResponse(
        "reader.html",
        {
            "request": request,
            "title": f"{comic['filename']} — {_library_title()}",
            "breadcrumbs": breadcrumbs,
            "comic_uuid": comic_uuid,
            "comic_title": comic["filename"],
            "page_count": page_count,
            "initial_page": initial_page,
            "reader_auth_enabled": _reader_auth_enabled(),
        },
    )


# --- API: comic info and page image ---


@router.get("/api/comic/{comic_uuid}")
def api_comic_info(comic_uuid: str):
    """JSON: comic title and page count."""
    comic = services.get_comic_by_uuid(comic_uuid)
    if not comic:
        raise HTTPException(status_code=404, detail="Comic not found")
    return {"title": comic["filename"], "page_count": comic["page_count"]}


@router.get("/api/comic/{comic_uuid}/page/{page_num:int}")
def api_comic_page(comic_uuid: str, page_num: int):
    """Image bytes for one page (1-based)."""
    if page_num < 1:
        raise HTTPException(status_code=404, detail="Page not found")
    result = services.get_page_image(comic_uuid, page_num - 1)
    if not result:
        raise HTTPException(status_code=404, detail="Page not found")
    data, content_type = result
    return Response(
        content=data,
        media_type=content_type,
        headers={"Cache-Control": "private, max-age=3600"},
    )


# --- API: metadata (info panel) ---


class MetadataUpdate(BaseModel):
    title: str | None = None
    series: str | None = None
    issue_number: int | None = None
    publisher: str | None = None
    year: int | None = None
    month: int | None = None
    writer: str | None = None
    penciller: str | None = None
    artist: str | None = None
    summary: str | None = None
    notes: str | None = None
    web: str | None = None
    language_iso: str | None = None
    score: int | None = None
    genre: str | None = None


@router.get("/api/comic/{comic_uuid}/metadata")
def api_comic_metadata_get(comic_uuid: str):
    """JSON: comic filename, uuid, and editable metadata."""
    with db_connection() as conn:
        out = repo.get_metadata(conn, comic_uuid)
        if out is None:
            raise HTTPException(status_code=404, detail="Comic not found")
        return out


@router.patch("/api/comic/{comic_uuid}/metadata")
def api_comic_metadata_patch(comic_uuid: str, body: MetadataUpdate):
    """Update editable metadata (partial)."""
    with db_connection() as conn:
        if repo.get_comic_id_by_uuid(conn, comic_uuid) is None:
            raise HTTPException(status_code=404, detail="Comic not found")
        payload = body.model_dump(exclude_unset=True)
        repo.update_metadata(conn, comic_uuid, payload)
        return {"ok": True}


# --- API: progress (continue reading) ---


class ProgressUpdate(BaseModel):
    current_page: int
    is_completed: bool | None = None


@router.get("/api/comic/{comic_uuid}/progress")
def api_comic_progress_get(comic_uuid: str):
    """JSON: current_page, is_completed, last_read_at."""
    with db_connection() as conn:
        out = repo.get_progress(conn, comic_uuid)
        if out is None:
            raise HTTPException(status_code=404, detail="Comic not found")
        return out


@router.patch("/api/comic/{comic_uuid}/progress")
def api_comic_progress_patch(comic_uuid: str, body: ProgressUpdate):
    """Update reading progress."""
    with db_connection() as conn:
        if repo.get_comic_id_by_uuid(conn, comic_uuid) is None:
            raise HTTPException(status_code=404, detail="Comic not found")
        repo.update_progress(conn, comic_uuid, body.current_page, body.is_completed)
        return {"ok": True}


@router.post("/api/comic/{comic_uuid}/progress/clear")
def api_comic_progress_clear(comic_uuid: str):
    """Remove from Continue Reading: reset progress."""
    with db_connection() as conn:
        if repo.get_comic_id_by_uuid(conn, comic_uuid) is None:
            raise HTTPException(status_code=404, detail="Comic not found")
        repo.clear_progress(conn, comic_uuid)
        return Response(content="", status_code=200)


# --- API: folder preview thumbnails ---


@router.get("/api/folder/{folder_id:int}/preview")
def api_folder_preview(folder_id: int, limit: int = 3):
    """JSON: list of comic UUIDs for folder preview stack."""
    with db_connection() as conn:
        folder = repo.get_folder(conn, folder_id)
        if not folder:
            raise HTTPException(status_code=404, detail="Folder not found")
        uuids = repo.get_folder_preview_thumbnails(conn, folder_id, min(limit, 5))
        return {"uuids": uuids}
