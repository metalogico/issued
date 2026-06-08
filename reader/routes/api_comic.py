"""Comic-level API routes: info, page, metadata, tags, progress."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel

from server.database import db_connection
from .. import repo
from .. import services

router = APIRouter(tags=["reader"])


# --- Pydantic models ---


class TagsUpdate(BaseModel):
    tags: list[str]


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


class ProgressUpdate(BaseModel):
    current_page: int
    is_completed: bool | None = None


# --- Comic info and page ---


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


# --- Metadata ---


@router.get("/api/comic/{comic_uuid}/metadata")
def api_comic_metadata_get(comic_uuid: str):
    """JSON: comic filename, uuid, editable metadata, and tags."""
    with db_connection() as conn:
        out = repo.get_metadata(conn, comic_uuid)
        if out is None:
            raise HTTPException(status_code=404, detail="Comic not found")
        out["tags"] = repo.get_tags_for_comic(conn, comic_uuid)
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


# --- Tags ---


@router.get("/api/comic/{comic_uuid}/tags")
def api_comic_tags_get(comic_uuid: str):
    """JSON: list of tags for a comic."""
    with db_connection() as conn:
        if repo.get_comic_id_by_uuid(conn, comic_uuid) is None:
            raise HTTPException(status_code=404, detail="Comic not found")
        tags = repo.get_tags_for_comic(conn, comic_uuid)
        return {"tags": tags}


@router.put("/api/comic/{comic_uuid}/tags")
def api_comic_tags_put(comic_uuid: str, body: TagsUpdate):
    """Replace tag list for a comic."""
    with db_connection() as conn:
        if repo.get_comic_id_by_uuid(conn, comic_uuid) is None:
            raise HTTPException(status_code=404, detail="Comic not found")
        tags = repo.set_tags_for_comic(conn, comic_uuid, body.tags)
        return {"ok": True, "tags": tags}


@router.get("/api/tags")
def api_tags_list():
    """JSON: all tag names in the library (for autocomplete)."""
    with db_connection() as conn:
        return {"tags": repo.get_all_tags(conn)}


@router.delete("/api/tags/{tag_name}")
def api_tag_delete(tag_name: str):
    """Delete a tag globally (removes it from all comics)."""
    with db_connection() as conn:
        found = repo.delete_tag(conn, tag_name)
    if not found:
        raise HTTPException(status_code=404, detail="Tag not found")
    return {"ok": True}


# --- Progress ---


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


@router.post("/api/comic/{comic_uuid}/completed/toggle")
def api_comic_completed_toggle(comic_uuid: str):
    """Toggle comic completed state."""
    with db_connection() as conn:
        if repo.get_comic_id_by_uuid(conn, comic_uuid) is None:
            raise HTTPException(status_code=404, detail="Comic not found")
        is_completed = repo.toggle_comic_completed(conn, comic_uuid)
        return {"ok": True, "is_completed": bool(is_completed)}
