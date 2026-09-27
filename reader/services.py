"""Reader services: comic lookup and page image extraction.

Uses Issued database and archive handling. Keeps reader logic separate from routes.
Supports CBZ, CBR, CB7, and PDF containers through the shared archive layer.
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


class PageNotFoundError(Exception):
    """Comic, file, or requested page does not exist."""


class PageExtractionError(Exception):
    """An existing page could not be extracted."""


class PageDependencyError(PageExtractionError):
    """A required archive backend is unavailable."""


def extract_page_image(comic_uuid: str, page_index: int) -> tuple[bytes, str]:
    """Read one 0-based page without counting pages separately or writing progress.

    The actual archive listing is authoritative, even with missing/stale DB counts.
    Errors are explicit so callers can choose their own HTTP contract.
    """
    if page_index < 0:
        raise PageNotFoundError()
    config = get_config()
    with db_connection() as conn:
        comic = conn.execute(
            "SELECT path FROM comics WHERE uuid = ?", (comic_uuid,)
        ).fetchone()
    if comic is None:
        raise PageNotFoundError()
    path = to_absolute(comic["path"], config.library_path)
    try:
        with get_archive(path) as archive:
            names = sorted(archive.list_images(), key=_natural_sort_key)
            if page_index >= len(names):
                raise PageNotFoundError()
            name = names[page_index]
            return archive.read(name), _CONTENT_TYPES.get(
                Path(name).suffix.lower(), "image/jpeg"
            )
    except PageNotFoundError:
        raise
    except FileNotFoundError as exc:
        raise PageNotFoundError() from exc
    except ImportError as exc:
        raise PageDependencyError() from exc
    except Exception as exc:
        # rarfile raises this when no external RAR extraction tool is available.
        from server.archive import rarfile

        if rarfile is not None and isinstance(exc, rarfile.RarCannotExec):
            raise PageDependencyError() from exc
        raise PageExtractionError() from exc


def get_page_image(comic_uuid: str, page_index: int) -> Optional[tuple[bytes, str]]:
    """Reader-compatible adapter: original bytes/MIME, None for unavailable pages."""
    try:
        return extract_page_image(comic_uuid, page_index)
    except (PageNotFoundError, PageExtractionError):
        return None
