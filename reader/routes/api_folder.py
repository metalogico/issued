"""Folder-level API routes: ongoing, preview, complete-all."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from server.database import db_connection
from .. import repo
from ._common import templates

router = APIRouter(tags=["reader"])


class OngoingUpdate(BaseModel):
    ongoing: bool


@router.patch("/api/folder/{folder_id:int}/ongoing")
def api_folder_ongoing_patch(folder_id: int, body: OngoingUpdate):
    """Mark or unmark a series folder as ongoing."""
    with db_connection() as conn:
        if not repo.get_folder(conn, folder_id):
            raise HTTPException(status_code=404, detail="Folder not found")
        if not repo.folder_is_leaf(conn, folder_id):
            raise HTTPException(
                status_code=400,
                detail="Only series folders (no subfolders) can be marked ongoing",
            )
        if body.ongoing and repo.folder_comic_count(conn, folder_id) == 0:
            raise HTTPException(status_code=400, detail="Folder has no comics")
        repo.set_ongoing_series(conn, folder_id, body.ongoing)
    return {"ok": True, "ongoing": body.ongoing}


@router.get("/api/folder/{folder_id:int}/preview")
def api_folder_preview(folder_id: int, limit: int = 3):
    """JSON: list of comic UUIDs for folder preview stack."""
    with db_connection() as conn:
        folder = repo.get_folder(conn, folder_id)
        if not folder:
            raise HTTPException(status_code=404, detail="Folder not found")
        uuids = repo.get_folder_preview_thumbnails(conn, folder_id, min(limit, 5))
        return {"uuids": uuids}


@router.post("/api/folder/{folder_id:int}/complete-all")
def api_folder_complete_all(folder_id: int, request: Request):
    """Mark all comics in a folder as completed."""
    with db_connection() as conn:
        folder = repo.get_folder(conn, folder_id)
        if not folder:
            raise HTTPException(status_code=404, detail="Folder not found")

        repo.mark_all_comics_in_folder_completed(conn, folder_id)

        comics = repo.get_comics_in_folder(conn, folder_id)

        return templates.TemplateResponse(
            request,
            "partials/comics-section.html",
            {
                "comics": comics,
                "grouped_comics": [],
                "is_search": False,
                "folder_id": folder_id,
            },
        )
