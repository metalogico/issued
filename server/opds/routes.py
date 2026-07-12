"""OPDS and misc FastAPI routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse

from ..config import get_config
from ..database import db_connection
from ..logging_config import get_logger
from .feeds import (
    _absolute_href,
    _comic_entry_xml,
    _comic_media_type,
    _escape_xml,
    _folder_href,
    _get_library_title,
    _now_iso,
    _recent_href,
    _root_href,
    _search_href,
    _xml_response,
)

logger = get_logger(__name__)

router = APIRouter()


@router.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    return Response(status_code=204)


@router.get("/.well-known/appspecific/com.chrome.devtools.json", include_in_schema=False)
def chrome_devtools_well_known() -> Response:
    return Response(content="{}", media_type="application/json")


@router.get("/opds")
def opds_root_no_slash(request: Request) -> Response:
    return opds_root(request)


@router.get("/opds/")
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


@router.get("/opds/folder/{folder_id}")
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

        cur = conn.execute(
            "SELECT id, name FROM folders WHERE parent_id = ? ORDER BY name",
            (folder_id,),
        )
        subfolders = cur.fetchall()

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

    is_series = len(subfolders) == 0
    series_folder_id = folder_id if is_series else None
    series_name = folder["name"] if is_series else None

    for comic in comics:
        updated_ts = comic["last_scanned_at"] or updated
        media_type = _comic_media_type(comic["format"])
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


@router.get("/opds/recent")
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
        media_type = _comic_media_type(comic["format"])
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


@router.get("/opds/search")
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
        media_type = _comic_media_type(comic["format"])
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


@router.get("/opds/comic/{comic_uuid}/file")
def download_comic(comic_uuid: str):
    """Return original comic archive."""
    from ..path_utils import to_absolute

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

    media_type = _comic_media_type(comic["format"])
    detected_suffix = f".{comic['format'].lower()}"
    download_name = (
        path.name
        if path.suffix.lower() == detected_suffix
        else f"{path.stem}{detected_suffix}"
    )
    return FileResponse(path, media_type=media_type, filename=download_name)


@router.get("/opds/comic/{comic_uuid}/thumbnail")
def get_thumbnail(comic_uuid: str):
    """Return WebP thumbnail for comic."""
    try:
        config = get_config()
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="Server not configured")

    thumb_path = config.thumbnails_dir / f"{comic_uuid}.webp"
    if not thumb_path.exists():
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    return FileResponse(thumb_path, media_type="image/webp")
