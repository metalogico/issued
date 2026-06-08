"""Browse and reader page routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from server.database import db_connection
from .. import repo
from .. import services
from ._common import templates, _library_title, _reader_auth_enabled, _folder_ongoing_context

router = APIRouter(tags=["reader"])


# --- Browse: root ---


@router.get("/")
def browse_root(request: Request):
    """Browse root: first level (single folder contents or folder list + last added)."""
    with db_connection() as conn:
        top_folders = repo.get_top_folders(conn)

        if len(top_folders) == 1:
            folder_id = top_folders[0]["id"]
            subfolders = repo.get_subfolders_with_item_count(conn, folder_id)
            comics = repo.get_comics_in_folder(conn, folder_id)
            continue_reading = repo.get_continue_reading_comics(conn, 12)
            ongoing_ctx = _folder_ongoing_context(conn, folder_id)
            return templates.TemplateResponse(
                request,
                "browser.html",
                {
                    "title": _library_title(),
                    "breadcrumbs": [],
                    "folders": subfolders,
                    "comics": comics,
                    "grouped_comics": [],
                    "is_search": False,
                    "show_last_added": False,
                    "last_added_comics": [],
                    "continue_reading_comics": continue_reading,
                    "reader_auth_enabled": _reader_auth_enabled(),
                    "folder_id": folder_id,
                    **ongoing_ctx,
                },
            )

        repo.add_folder_item_counts(conn, top_folders)
        continue_reading = repo.get_continue_reading_comics(conn, 12)
        return templates.TemplateResponse(
            request,
            "browser.html",
            {
                "title": _library_title(),
                "breadcrumbs": [],
                "folders": top_folders,
                "comics": [],
                "grouped_comics": [],
                "is_search": False,
                "show_last_added": False,
                "last_added_comics": [],
                "continue_reading_comics": continue_reading,
                "reader_auth_enabled": _reader_auth_enabled(),
                "folder_id": None,
                "is_leaf": False,
                "is_ongoing": False,
            },
        )


# --- Browse: search ---


@router.get("/search")
def browse_search(request: Request, q: str = ""):
    """Search comics by filename or metadata."""
    with db_connection() as conn:
        grouped_comics = repo.search_comics_grouped(conn, q)

    return templates.TemplateResponse(
        request,
        "browser.html",
        {
            "title": f"Search: {q} — {_library_title()}",
            "breadcrumbs": [],
            "folders": [],
            "comics": [],
            "grouped_comics": grouped_comics,
            "is_search": True,
            "show_last_added": False,
            "last_added_comics": [],
            "continue_reading_comics": [],
            "reader_auth_enabled": _reader_auth_enabled(),
            "folder_id": None,
            "is_leaf": False,
            "is_ongoing": False,
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
        request,
        "browser.html",
        {
            "title": f"Last added — {_library_title()}",
            "breadcrumbs": [],
            "folders": [],
            "comics": comics,
            "grouped_comics": [],
            "is_search": False,
            "show_last_added": False,
            "last_added_comics": [],
            "continue_reading_comics": [],
            "reader_auth_enabled": _reader_auth_enabled(),
            "folder_id": None,
            "is_leaf": False,
            "is_ongoing": False,
        },
    )


# --- Browse: ongoing series ---


@router.get("/ongoings")
def browse_ongoings(request: Request):
    """List series marked ongoing with counts, last issue, gap hints."""
    with db_connection() as conn:
        ongoing_rows = repo.list_ongoing_series_rows(conn)
    return templates.TemplateResponse(
        request,
        "ongoings.html",
        {
            "title": _library_title(),
            "ongoing_rows": ongoing_rows,
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
        ongoing_ctx = _folder_ongoing_context(conn, folder_id)

    return templates.TemplateResponse(
        request,
        "browser.html",
        {
            "title": f"{folder['name']} — {_library_title()}",
            "breadcrumbs": breadcrumbs,
            "folders": subfolders,
            "comics": comics,
            "grouped_comics": [],
            "is_search": False,
            "show_last_added": False,
            "last_added_comics": [],
            "continue_reading_comics": [],
            "reader_auth_enabled": _reader_auth_enabled(),
            "folder_id": folder_id,
            **ongoing_ctx,
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
        metadata = repo.get_metadata(conn, comic_uuid)
        issue_title = (metadata or {}).get("title")

    return templates.TemplateResponse(
        request,
        "reader.html",
        {
            "title": f"{comic['filename']} — {_library_title()}",
            "breadcrumbs": breadcrumbs,
            "comic_uuid": comic_uuid,
            "comic_filename": comic["filename"],
            "issue_title": issue_title,
            "page_count": page_count,
            "initial_page": initial_page,
            "reader_auth_enabled": _reader_auth_enabled(),
        },
    )


# --- Browse: tags ---


@router.get("/tags")
def browse_tags(request: Request):
    """Tag index: all tags with comic counts."""
    with db_connection() as conn:
        tag_rows = repo.get_all_tags_with_counts(conn)
    return templates.TemplateResponse(
        request,
        "tags.html",
        {
            "title": f"Tags — {_library_title()}",
            "tag_rows": tag_rows,
            "reader_auth_enabled": _reader_auth_enabled(),
        },
    )


@router.get("/tags/{tag_name}")
def browse_tag(request: Request, tag_name: str):
    """Browse all comics with a given tag."""
    with db_connection() as conn:
        grouped_comics = repo.get_comics_for_tag(conn, tag_name)
    return templates.TemplateResponse(
        request,
        "browser.html",
        {
            "title": f"Tag: {tag_name} — {_library_title()}",
            "breadcrumbs": [],
            "folders": [],
            "comics": [],
            "grouped_comics": grouped_comics,
            "is_search": True,
            "show_last_added": False,
            "last_added_comics": [],
            "continue_reading_comics": [],
            "reader_auth_enabled": _reader_auth_enabled(),
            "folder_id": None,
            "is_leaf": False,
            "is_ongoing": False,
        },
    )
