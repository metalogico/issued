"""Metadata read/write queries for the web reader."""

from __future__ import annotations


def get_comic_id_by_uuid(conn, comic_uuid: str) -> int | None:
    """Comic id for uuid, or None."""
    cur = conn.execute("SELECT id FROM comics WHERE uuid = ?", (comic_uuid,))
    row = cur.fetchone()
    return row["id"] if row else None


def get_folder_id_for_comic(conn, comic_uuid: str) -> int | None:
    """Folder id for comic, or None."""
    cur = conn.execute("SELECT folder_id FROM comics WHERE uuid = ?", (comic_uuid,))
    row = cur.fetchone()
    return row["folder_id"] if row and row["folder_id"] is not None else None


def get_initial_page(conn, comic_uuid: str, page_count: int) -> int:
    """1-based page from metadata, clamped to [1, page_count]."""
    cur = conn.execute(
        "SELECT m.current_page FROM comics c INNER JOIN metadata m ON m.comic_id = c.id WHERE c.uuid = ?",
        (comic_uuid,),
    )
    row = cur.fetchone()
    if not row or row["current_page"] is None:
        return 1
    p = int(row["current_page"])
    return max(1, min(p, page_count)) if page_count else 1


def get_metadata(conn, comic_uuid: str) -> dict | None:
    """Full metadata dict for comic (filename, uuid, all meta fields). None if comic not found."""
    cur = conn.execute(
        "SELECT id, uuid, filename FROM comics WHERE uuid = ?",
        (comic_uuid,),
    )
    row = cur.fetchone()
    if not row:
        return None
    comic_id = row["id"]
    cur = conn.execute(
        "SELECT title, series, issue_number, publisher, year, month, writer, penciller, artist, "
        "summary, notes, web, language_iso, score, genre "
        "FROM metadata WHERE comic_id = ?",
        (comic_id,),
    )
    meta = cur.fetchone()
    out = {
        "uuid": row["uuid"],
        "filename": row["filename"],
        "title": None,
        "series": None,
        "issue_number": None,
        "publisher": None,
        "year": None,
        "month": None,
        "writer": None,
        "penciller": None,
        "artist": None,
        "summary": None,
        "notes": None,
        "web": None,
        "language_iso": None,
        "score": None,
        "genre": None,
    }
    if meta:
        for k in out:
            if k in ("uuid", "filename"):
                continue
            if k in meta.keys():
                out[k] = meta[k]
    return out


def ensure_metadata_row(conn, comic_id: int) -> None:
    """Insert metadata row for comic_id if missing."""
    cur = conn.execute("SELECT 1 FROM metadata WHERE comic_id = ?", (comic_id,))
    if not cur.fetchone():
        conn.execute("INSERT INTO metadata (comic_id) VALUES (?)", (comic_id,))
        conn.commit()


_ALLOWED_METADATA_COLUMNS = frozenset({
    "title", "series", "issue_number", "publisher", "year", "month",
    "writer", "penciller", "artist", "summary", "notes", "web",
    "language_iso", "score", "genre",
})


def update_metadata(conn, comic_uuid: str, payload: dict) -> None:
    """Update metadata fields. payload: dict of column -> value. Creates row if needed."""
    comic_id = get_comic_id_by_uuid(conn, comic_uuid)
    if not comic_id:
        return
    ensure_metadata_row(conn, comic_id)
    safe_payload = {k: v for k, v in payload.items() if k in _ALLOWED_METADATA_COLUMNS}
    if not safe_payload:
        return
    updates = [f"{k} = ?" for k in safe_payload]
    params = list(safe_payload.values()) + [comic_id]
    conn.execute(
        "UPDATE metadata SET " + ", ".join(updates) + " WHERE comic_id = ?",
        tuple(params),
    )
    conn.commit()
