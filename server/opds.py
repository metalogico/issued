"""FastAPI OPDS server for Issued.

Exposes:
- GET /opds/                  (root navigation)
- GET /opds/folder/{folder_id}
- GET /opds/recent
- GET /opds/search
- GET /opds/comic/{comic_uuid}/file
- GET /opds/comic/{comic_uuid}/thumbnail
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
import uvicorn

from .logging_config import get_logger

logger = get_logger(__name__)

from .config import IssuedConfig, get_config
from .database import DB_PATH, db_connection

from reader import auth as reader_auth
from reader import router as reader_router
from reader.router import STATIC_DIR


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
            logger = logging.getLogger("issued.request")
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
            logger.info(message)
            request.app.state.logged_first_request = True
        return await call_next(request)


def _info(msg: str) -> None:
    logger.info(msg)


def _get_lan_ip() -> Optional[str]:
    """Return this machine's LAN IP (for OPDS URL when binding to 0.0.0.0)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return None


@asynccontextmanager
async def _lifespan(app: FastAPI):
    async def _print_startup_messages():
        await asyncio.sleep(0.1)
        _info("Started server process [" + str(os.getpid()) + "]")
        _info("Application startup complete. (Press CTRL+C to quit)")
        opds_url = getattr(app.state, "opds_url_public", None)
        if opds_url:
            _info("OPDS server available at: " + opds_url)
        reader_url = getattr(app.state, "reader_url", None)
        if reader_url:
            _info("Web reader: " + reader_url)
        if getattr(app.state, "monitoring_enabled", False):
            _info("File monitoring enabled")

    asyncio.create_task(_print_startup_messages())
    yield


app = FastAPI(title="Issued OPDS", lifespan=_lifespan)
app.add_middleware(ReaderAuthMiddleware)
app.add_middleware(RequestLoggingMiddleware)

app.include_router(reader_router, prefix="/reader")
app.mount("/reader/static", StaticFiles(directory=str(STATIC_DIR)), name="reader_static")


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    return Response(status_code=204)


@app.get("/.well-known/appspecific/com.chrome.devtools.json", include_in_schema=False)
def chrome_devtools_well_known() -> Response:
    return Response(content="{}", media_type="application/json")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _root_href() -> str:
    return "/opds/"


def _folder_href(folder_id: int) -> str:
    return f"/opds/folder/{folder_id}"


def _comic_file_href(comic_uuid: str) -> str:
    return f"/opds/comic/{comic_uuid}/file"


def _comic_thumb_href(comic_uuid: str) -> str:
    return f"/opds/comic/{comic_uuid}/thumbnail"


def _absolute_href(base_url: str, path: str) -> str:
    return base_url.rstrip("/") + path


def _comic_entry_xml(
    comic_uuid: str,
    title: str,
    updated_ts: str,
    media_type: str,
    base_url: str,
    *,
    series_folder_id: Optional[int] = None,
    series_name: Optional[str] = None,
) -> str:
    """Build OPDS entry XML for a comic. Adds rel=collection when folder is a series (leaf)."""
    links = [
        f'    <link rel="http://opds-spec.org/image/thumbnail"'
        f'          href="{_absolute_href(base_url, _comic_thumb_href(comic_uuid))}" type="image/jpeg" />',
        f'    <link rel="http://opds-spec.org/acquisition"'
        f'          href="{_absolute_href(base_url, _comic_file_href(comic_uuid))}" type="{media_type}" />',
    ]
    if series_folder_id is not None and series_name is not None:
        links.insert(
            1,
            f'    <link rel="collection"'
            f'          href="{_absolute_href(base_url, _folder_href(series_folder_id))}"'
            f'          type="application/atom+xml;profile=opds-catalog;kind=acquisition"'
            f'          title="{_escape_xml(series_name)}" />',
        )
    links_str = "\n".join(links)
    return f"""
  <entry>
    <title>{_escape_xml(title)}</title>
    <id>urn:comic:{comic_uuid}</id>
    <updated>{updated_ts}</updated>
{links_str}
  </entry>"""


def _escape_xml(s: str) -> str:
    """Escape &, <, >, ", ' for XML text/attributes."""
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _recent_href(limit: int) -> str:
    return f"/opds/recent?limit={limit}"


def _search_href(q: str) -> str:
    return f"/opds/search?q={quote(q)}"


def _xml_response(xml: str) -> Response:
    return Response(
        content=xml,
        media_type="application/atom+xml;profile=opds-catalog",
    )


def _get_library_title(config: IssuedConfig | None) -> str:
    if config is None:
        return "Issued Library"
    return config.library.name


@app.get("/opds")
def opds_root_no_slash(request: Request) -> Response:
    return opds_root(request)


@app.get("/opds/")
def opds_root(request: Request) -> Response:
    """Root navigation feed: top-level folders + recent link."""
    try:
        config = get_config()
    except FileNotFoundError:
        logger.error("config.ini not found while serving OPDS root")
        raise HTTPException(status_code=500, detail="Server not configured")

    with db_connection() as conn:
        cur = conn.execute(
            "SELECT id, name FROM folders WHERE parent_id IS NULL ORDER BY name"
        )
        folders = cur.fetchall()

    updated = _now_iso()
    base_url = str(request.base_url)
    self_href = _absolute_href(base_url, _root_href())
    title = _get_library_title(config)

    entries = []
    for folder in folders:
        entries.append(
            f"""
  <entry>
    <title>{_escape_xml(folder['name'])}</title>
    <id>urn:folder:{folder['id']}</id>
    <updated>{updated}</updated>
    <link rel="subsection"
          href="{_absolute_href(base_url, _folder_href(folder['id']))}"
          type="application/atom+xml;profile=opds-catalog" />
  </entry>"""
        )

    # Recent link as navigation entry
    entries.append(
        f"""
  <entry>
    <title>Recent</title>
    <id>urn:recent</id>
    <updated>{updated}</updated>
    <link rel="subsection"
          href="{_absolute_href(base_url, _recent_href(50))}"
          type="application/atom+xml;profile=opds-catalog" />
  </entry>"""
    )

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<feed xmlns="http://www.w3.org/2005/Atom">\n'
        f"  <id>urn:uuid:root</id>\n"
        f"  <title>{title}</title>\n"
        f"  <updated>{updated}</updated>\n"
        f"  <link rel=\"self\" href=\"{self_href}\" type=\"application/atom+xml;profile=opds-catalog\" />\n"
        f"  <link rel=\"start\" href=\"{self_href}\" type=\"application/atom+xml;profile=opds-catalog\" />\n"
        f"{''.join(entries)}\n"
        "</feed>"
    )
    return _xml_response(xml)


@app.get("/opds/folder/{folder_id}")
def opds_folder(folder_id: int, request: Request) -> Response:
    """Acquisition feed for a folder: subfolders + comics."""
    with db_connection() as conn:
        cur = conn.execute(
            "SELECT id, name, path FROM folders WHERE id = ?",
            (folder_id,),
        )
        folder = cur.fetchone()
        if not folder:
            raise HTTPException(status_code=404, detail="Folder not found")

        # Subfolders
        cur = conn.execute(
            "SELECT id, name FROM folders WHERE parent_id = ? ORDER BY name",
            (folder_id,),
        )
        subfolders = cur.fetchall()

        # Comics in this folder (metadata.title used for display when present)
        cur = conn.execute(
            "SELECT c.id, c.uuid, c.filename, c.format, c.last_scanned_at, "
            "       COALESCE(m.title, c.filename) AS display_title "
            "FROM comics c "
            "LEFT JOIN metadata m ON m.comic_id = c.id "
            "WHERE c.folder_id = ? ORDER BY c.filename",
            (folder_id,),
        )
        comics = cur.fetchall()

    updated = _now_iso()
    base_url = str(request.base_url)
    self_href = _absolute_href(base_url, _folder_href(folder_id))
    start_href = _absolute_href(base_url, _root_href())
    entries = []
    for sub in subfolders:
        entries.append(
            f"""
  <entry>
    <title>{_escape_xml(sub['name'])}</title>
    <id>urn:folder:{sub['id']}</id>
    <updated>{updated}</updated>
    <link rel="subsection"
          href="{_absolute_href(base_url, _folder_href(sub['id']))}"
          type="application/atom+xml;profile=opds-catalog" />
  </entry>"""
        )

    # Leaf folder = no subfolders = series (all comics belong to this series)
    is_series = len(subfolders) == 0
    series_folder_id = folder_id if is_series else None
    series_name = folder["name"] if is_series else None

    for comic in comics:
        updated_ts = comic["last_scanned_at"] or updated
        media_type = (
            "application/x-cbz"
            if comic["format"].lower() == "cbz"
            else "application/x-cbr"
        )
        comic_uuid = comic["uuid"]
        title = comic["display_title"] or comic["filename"]
        entries.append(
            _comic_entry_xml(
                comic_uuid,
                title,
                updated_ts,
                media_type,
                base_url,
                series_folder_id=series_folder_id,
                series_name=series_name,
            )
        )

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<feed xmlns="http://www.w3.org/2005/Atom">\n'
        f"  <id>urn:folder:{folder_id}</id>\n"
        f"  <title>{_escape_xml(folder['name'])}</title>\n"
        f"  <updated>{updated}</updated>\n"
        f"  <link rel=\"self\" href=\"{self_href}\" type=\"application/atom+xml;profile=opds-catalog\" />\n"
        f"  <link rel=\"start\" href=\"{start_href}\" type=\"application/atom+xml;profile=opds-catalog\" />\n"
        f"{''.join(entries)}\n"
        "</feed>"
    )
    return _xml_response(xml)


@app.get("/opds/recent")
def opds_recent(request: Request, limit: int = Query(50, ge=1, le=200)) -> Response:
    """Acquisition feed of recent comics."""
    with db_connection() as conn:
        cur = conn.execute(
            "SELECT c.id, c.uuid, c.filename, c.format, c.last_scanned_at, "
            "       c.folder_id, f.name AS folder_name, "
            "       COALESCE(m.title, c.filename) AS display_title "
            "FROM comics c "
            "JOIN folders f ON c.folder_id = f.id "
            "LEFT JOIN metadata m ON m.comic_id = c.id "
            "ORDER BY c.last_scanned_at DESC LIMIT ?",
            (limit,),
        )
        comics = cur.fetchall()
        folder_ids = [c["folder_id"] for c in comics]
        non_leaf_ids = set()
        if folder_ids:
            placeholders = ",".join("?" * len(folder_ids))
            cur = conn.execute(
                f"SELECT parent_id FROM folders WHERE parent_id IN ({placeholders})",
                folder_ids,
            )
            non_leaf_ids = {row["parent_id"] for row in cur.fetchall()}

    updated = _now_iso()
    base_url = str(request.base_url)
    self_href = _absolute_href(base_url, _recent_href(limit))
    start_href = _absolute_href(base_url, _root_href())
    
    entries = []
    for comic in comics:
        updated_ts = comic["last_scanned_at"] or updated
        media_type = (
            "application/x-cbz"
            if comic["format"].lower() == "cbz"
            else "application/x-cbr"
        )
        comic_uuid = comic["uuid"]
        title = comic["display_title"] or comic["filename"]
        is_series = comic["folder_id"] not in non_leaf_ids
        entries.append(
            _comic_entry_xml(
                comic_uuid,
                title,
                updated_ts,
                media_type,
                base_url,
                series_folder_id=comic["folder_id"] if is_series else None,
                series_name=comic["folder_name"] if is_series else None,
            )
        )

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<feed xmlns="http://www.w3.org/2005/Atom">\n'
        "  <id>urn:recent</id>\n"
        "  <title>Recent</title>\n"
        f"  <updated>{updated}</updated>\n"
        f"  <link rel=\"self\" href=\"{self_href}\" type=\"application/atom+xml;profile=opds-catalog\" />\n"
        f"  <link rel=\"start\" href=\"{start_href}\" type=\"application/atom+xml;profile=opds-catalog\" />\n"
        f"{''.join(entries)}\n"
        "</feed>"
    )
    return _xml_response(xml)


@app.get("/opds/search")
def opds_search(request: Request, q: str = Query(..., min_length=1)) -> Response:
    """Search by filename and metadata (title, series, writer, notes, summary, etc.)."""
    like = f"%{q}%"

    with db_connection() as conn:
        cur = conn.execute(
            "SELECT c.id, c.uuid, c.filename, c.format, c.last_scanned_at, "
            "       c.folder_id, f.name AS folder_name, "
            "       COALESCE(m.title, c.filename) AS display_title "
            "FROM comics c "
            "JOIN folders f ON c.folder_id = f.id "
            "LEFT JOIN metadata m ON m.comic_id = c.id "
            "WHERE c.filename LIKE ? OR m.title LIKE ? OR m.series LIKE ? "
            "   OR m.writer LIKE ? OR m.penciller LIKE ? OR m.notes LIKE ? "
            "   OR m.summary LIKE ? OR m.genre LIKE ? OR m.publisher LIKE ? "
            "ORDER BY c.filename",
            (like, like, like, like, like, like, like, like, like),
        )
        comics = cur.fetchall()
        folder_ids = list({c["folder_id"] for c in comics})
        non_leaf_ids = set()
        if folder_ids:
            placeholders = ",".join("?" * len(folder_ids))
            cur = conn.execute(
                f"SELECT parent_id FROM folders WHERE parent_id IN ({placeholders})",
                folder_ids,
            )
            non_leaf_ids = {row["parent_id"] for row in cur.fetchall()}

    updated = _now_iso()
    base_url = str(request.base_url)
    self_href = _absolute_href(base_url, _search_href(q))
    start_href = _absolute_href(base_url, _root_href())
    entries = []
    for comic in comics:
        updated_ts = comic["last_scanned_at"] or updated
        media_type = (
            "application/x-cbz"
            if comic["format"].lower() == "cbz"
            else "application/x-cbr"
        )
        comic_uuid = comic["uuid"]
        title = comic["display_title"] or comic["filename"]
        is_series = comic["folder_id"] not in non_leaf_ids
        entries.append(
            _comic_entry_xml(
                comic_uuid,
                title,
                updated_ts,
                media_type,
                base_url,
                series_folder_id=comic["folder_id"] if is_series else None,
                series_name=comic["folder_name"] if is_series else None,
            )
        )

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<feed xmlns="http://www.w3.org/2005/Atom">\n'
        "  <id>urn:search</id>\n"
        f"  <title>Search: {_escape_xml(q)}</title>\n"
        f"  <updated>{updated}</updated>\n"
        f"  <link rel=\"self\" href=\"{self_href}\" type=\"application/atom+xml;profile=opds-catalog\" />\n"
        f"  <link rel=\"start\" href=\"{start_href}\" type=\"application/atom+xml;profile=opds-catalog\" />\n"
        f"{''.join(entries)}\n"
        "</feed>"
    )
    return _xml_response(xml)


@app.get("/opds/comic/{comic_uuid}/file")
def download_comic(comic_uuid: str):
    """Return original comic archive."""
    from .path_utils import to_absolute

    with db_connection() as conn:
        cur = conn.execute(
            "SELECT path, format FROM comics WHERE uuid = ?",
            (comic_uuid,),
        )
        comic = cur.fetchone()

    if not comic:
        raise HTTPException(status_code=404, detail="Comic not found")

    try:
        config = get_config()
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="Server not configured")

    path = to_absolute(comic["path"], config.library_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="File missing on disk")

    media_type = (
        "application/x-cbz"
        if comic["format"].lower() == "cbz"
        else "application/x-cbr"
    )
    return FileResponse(path, media_type=media_type, filename=path.name)


@app.get("/opds/comic/{comic_uuid}/thumbnail")
def get_thumbnail(comic_uuid: str):
    """Return JPEG thumbnail for comic."""
    try:
        config = get_config()
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="Server not configured")

    thumb_path = config.thumbnails_dir / f"{comic_uuid}.jpg"
    if not thumb_path.exists():
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    return FileResponse(thumb_path, media_type="image/jpeg")


class _ReaderAccessFilter(logging.Filter):
    """Filter out access log lines for successful requests to reduce console noise.
    Keep errors (4xx, 5xx) visible for debugging.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
            # Hide successful responses (200 OK, 304 Not Modified, etc.)
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
            # Keep errors visible (404, 500, etc.)
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


def run_server(
    config: IssuedConfig,
    host: Optional[str],
    port: Optional[int],
    monitoring_enabled: bool = False,
) -> None:
    """Run the FastAPI app with Uvicorn."""
    import uvicorn

    effective_host = host or config.server_host
    effective_port = port or config.server_port

    # Web reader: localhost is fine
    app.state.reader_url = f"http://localhost:{effective_port}/reader"
    app.state.monitoring_enabled = monitoring_enabled

    # OPDS: show network IP when binding to 0.0.0.0 so clients know where to connect
    if effective_host == "0.0.0.0":
        lan_ip = _get_lan_ip()
        opds_host = lan_ip if lan_ip else "0.0.0.0"
    else:
        opds_host = effective_host
    app.state.opds_url_public = f"http://{opds_host}:{effective_port}/opds/"

    startup_filter = _UvicornStartupFilter()
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "uvicorn.lifespan"):
        logging.getLogger(name).addFilter(startup_filter)
    logging.getLogger().addFilter(startup_filter)
    logging.getLogger("uvicorn.access").addFilter(_ReaderAccessFilter())

    uvicorn.run(
        app,
        host=effective_host,
        port=effective_port,
        log_level="info",
        log_config=None,
    )

