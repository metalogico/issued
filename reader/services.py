"""Reader services: comic lookup and page image extraction.

Uses Issued database and archive handling. Keeps reader logic separate from routes.
Page order: natural sort (1, 2, 3, ..., 10).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from server.config import get_config
from server.database import db_connection
from server.path_utils import to_absolute
from server.archive import get_archive

_CONTENT_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


def _natural_sort_key(name: str):
    """Sort key for image names so 1, 2, 10 order correctly (not 1, 10, 2)."""
    parts = re.split(r"(\d+)", name)
    return [
        int(part) if part.isdigit() else part.lower()
        for part in parts
    ]


def get_comic_by_uuid(comic_uuid: str) -> Optional[dict]:
    """Return comic info by UUID: path (absolute), page_count, filename. None if not found."""
    config = get_config()
    with db_connection() as conn:
        cur = conn.execute(
            "SELECT path, page_count, filename FROM comics WHERE uuid = ?",
            (comic_uuid,),
        )
        row = cur.fetchone()

    if not row:
        return None

    abs_path = to_absolute(row["path"], config.library_path)
    if not abs_path.exists():
        return None

    page_count = row["page_count"] or 0
    if page_count <= 0:
        try:
            with get_archive(abs_path) as archive:
                page_count = len(archive.list_images())
        except Exception:
            page_count = 0

    return {
        "path": abs_path,
        "page_count": page_count,
        "filename": row["filename"],
    }


def get_page_image(comic_uuid: str, page_index: int) -> Optional[tuple[bytes, str]]:
    """Return (image_bytes, content_type) for comic page at 0-based index.

    Extracts the single requested page directly from the archive.
    """
    if page_index < 0:
        return None

    comic = get_comic_by_uuid(comic_uuid)
    if not comic:
        return None

    try:
        with get_archive(comic["path"]) as archive:
            names = archive.list_images()
            names.sort(key=_natural_sort_key)
            if page_index >= len(names):
                return None
            name = names[page_index]
            data = archive.read(name)
            suffix = Path(name).suffix.lower()
            content_type = _CONTENT_TYPES.get(suffix, "image/jpeg")
            return data, content_type
    except Exception:
        return None
