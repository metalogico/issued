"""Data access layer for the web reader: all DB queries in one place."""

from __future__ import annotations

from datetime import datetime, timezone

# --- Folders ---


def get_top_folders(conn) -> list[dict]:
    """Top-level folders (parent_id IS NULL), ordered by name."""
    cur = conn.execute(
        "SELECT id, name FROM folders WHERE parent_id IS NULL ORDER BY name"
    )
    return [dict(row) for row in cur.fetchall()]


def add_folder_item_counts(conn, folders: list[dict]) -> None:
    """Mutate each folder dict adding item_count (subfolders + comics)."""
    for f in folders:
        cur = conn.execute(
            "SELECT (SELECT COUNT(*) FROM folders WHERE parent_id = ?) + (SELECT COUNT(*) FROM comics WHERE folder_id = ?)",
            (f["id"], f["id"]),
        )
        f["item_count"] = cur.fetchone()[0]


def get_folder(conn, folder_id: int) -> dict | None:
    """Single folder by id, or None if not found."""
    cur = conn.execute(
        "SELECT id, name, path, parent_id FROM folders WHERE id = ?",
        (folder_id,),
    )
    row = cur.fetchone()
    return dict(row) if row else None


def get_subfolders_with_item_count(conn, folder_id: int) -> list[dict]:
    """Direct subfolders of folder_id with item_count set."""
    cur = conn.execute(
        "SELECT id, name FROM folders WHERE parent_id = ? ORDER BY name",
        (folder_id,),
    )
    subfolders = [dict(row) for row in cur.fetchall()]
    add_folder_item_counts(conn, subfolders)
    return subfolders


def get_breadcrumbs_for_folder(conn, folder_id: int) -> list[dict]:
    """Breadcrumb chain for folder (excludes root). Each item: {id, name}."""
    chain = []
    current_id = folder_id
    while current_id:
        cur = conn.execute(
            "SELECT id, name, parent_id FROM folders WHERE id = ?",
            (current_id,),
        )
        folder = cur.fetchone()
        if not folder:
            break
        if folder["parent_id"] is not None:
            chain.append({"id": folder["id"], "name": folder["name"]})
        current_id = folder["parent_id"]
    chain.reverse()
    return chain


def get_folder_preview_thumbnails(conn, folder_id: int, limit: int = 3) -> list[str]:
    """Comic UUIDs for folder preview stack.
    - Leaf folder (series): last N added comics; if only 1 comic → 1 UUID (single cover).
    - Container with 1 direct child (1 subfolder): 1 UUID (single cover), last added in subtree.
    - Container with 2+ direct children: up to limit UUIDs, one per child when possible.
    """
    # Check if folder is leaf (no subfolders)
    cur = conn.execute(
        "SELECT COUNT(*) as cnt FROM folders WHERE parent_id = ?",
        (folder_id,),
    )
    direct_children_count = cur.fetchone()["cnt"]
    has_subfolders = direct_children_count > 0

    if not has_subfolders:
        # Leaf folder (series): get last N added comics
        cur = conn.execute(
            """
            SELECT c.uuid FROM comics c
            WHERE c.folder_id = ?
            ORDER BY c.last_scanned_at DESC
            LIMIT ?
            """,
            (folder_id, limit),
        )
        return [row["uuid"] for row in cur.fetchall()]

    # Container with exactly 1 direct child → show single cover (last added in subtree)
    if direct_children_count == 1:
        cur = conn.execute(
            """
            WITH RECURSIVE folder_tree AS (
                SELECT id FROM folders WHERE parent_id = ?
                UNION ALL
                SELECT f.id FROM folders f
                INNER JOIN folder_tree ft ON f.parent_id = ft.id
            )
            SELECT c.uuid FROM comics c
            WHERE c.folder_id IN (SELECT id FROM folder_tree)
            ORDER BY c.last_scanned_at DESC
            LIMIT 1
            """,
            (folder_id,),
        )
        row = cur.fetchone()
        return [row["uuid"]] if row else []

    # Container with 2+ direct children: diversify (one per child, then fill)
    cur = conn.execute(
        """
        WITH RECURSIVE folder_tree AS (
            SELECT id, id as root_child FROM folders WHERE parent_id = ?
            UNION ALL
            SELECT f.id, ft.root_child FROM folders f
            INNER JOIN folder_tree ft ON f.parent_id = ft.id
        )
        SELECT c.uuid, ft.root_child FROM comics c
        INNER JOIN folder_tree ft ON c.folder_id = ft.id
        ORDER BY RANDOM()
        """,
        (folder_id,),
    )
    rows = cur.fetchall()

    seen_children = set()
    result = []

    for row in rows:
        if len(result) >= limit:
            break
        child = row["root_child"]
        if child not in seen_children:
            result.append(row["uuid"])
            seen_children.add(child)

    if len(result) < limit:
        for row in rows:
            if len(result) >= limit:
                break
            if row["uuid"] not in result:
                result.append(row["uuid"])

    return result


# --- Comics (lists for browser) ---

_COMICS_WITH_META = """
    SELECT c.uuid, c.filename, c.page_count, (m.is_completed = 1) AS is_completed
    FROM comics c LEFT JOIN metadata m ON m.comic_id = c.id
"""


def get_comics_in_folder(conn, folder_id: int) -> list[dict]:
    """Comics in folder with is_completed."""
    cur = conn.execute(
        _COMICS_WITH_META + " WHERE c.folder_id = ? ORDER BY c.filename",
        (folder_id,),
    )
    return [dict(row) for row in cur.fetchall()]


def get_last_added_comics(conn, limit: int = 24) -> list[dict]:
    """Comics ordered by last_scanned_at DESC with is_completed."""
    cur = conn.execute(
        _COMICS_WITH_META + " ORDER BY c.last_scanned_at DESC LIMIT ?",
        (limit,),
    )
    return [dict(row) for row in cur.fetchall()]


def get_continue_reading_comics(conn, limit: int = 12) -> list[dict]:
    """Comics in progress (not completed), with current_page and is_completed."""
    cur = conn.execute(
        """SELECT c.uuid, c.filename, c.page_count, m.current_page, (m.is_completed = 1) AS is_completed
           FROM comics c INNER JOIN metadata m ON m.comic_id = c.id
           WHERE (m.current_page IS NOT NULL AND m.current_page > 0 OR m.last_read_at IS NOT NULL)
             AND (m.is_completed IS NULL OR m.is_completed = 0)
           ORDER BY m.last_read_at IS NULL, m.last_read_at DESC
           LIMIT ?""",
        (limit,),
    )
    return [dict(row) for row in cur.fetchall()]


def search_comics(conn, q: str) -> list[dict]:
    """Comics matching q in filename/title/series, with is_completed."""
    if not q or not q.strip():
        return []
    like = f"%{q.strip()}%"
    cur = conn.execute(
        _COMICS_WITH_META
        + " WHERE c.filename LIKE ? OR m.title LIKE ? OR m.series LIKE ? ORDER BY c.filename",
        (like, like, like),
    )
    return [dict(row) for row in cur.fetchall()]


# --- Comic by UUID (reader, APIs) ---


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


# --- Metadata (info panel) ---


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


# --- Progress (continue reading) ---


def get_progress(conn, comic_uuid: str) -> dict | None:
    """current_page, is_completed, last_read_at. None if comic not found."""
    comic_id = get_comic_id_by_uuid(conn, comic_uuid)
    if not comic_id:
        return None
    cur = conn.execute(
        "SELECT current_page, is_completed, last_read_at FROM metadata WHERE comic_id = ?",
        (comic_id,),
    )
    meta = cur.fetchone()
    out = {"current_page": 1, "is_completed": False, "last_read_at": None}
    if meta:
        out["current_page"] = meta["current_page"] if meta["current_page"] is not None else 1
        out["is_completed"] = bool(meta["is_completed"]) if meta["is_completed"] is not None else False
        out["last_read_at"] = meta["last_read_at"]
    return out


def update_progress(conn, comic_uuid: str, current_page: int, is_completed: bool | None) -> None:
    """Set current_page, last_read_at=now, optionally is_completed. Creates metadata row if needed."""
    comic_id = get_comic_id_by_uuid(conn, comic_uuid)
    if not comic_id:
        return
    ensure_metadata_row(conn, comic_id)
    now = datetime.now(timezone.utc).isoformat()
    updates = ["current_page = ?", "last_read_at = ?"]
    params = [current_page, now]
    if is_completed is not None:
        updates.append("is_completed = ?")
        params.append(1 if is_completed else 0)
    params.append(comic_id)
    conn.execute(
        "UPDATE metadata SET " + ", ".join(updates) + " WHERE comic_id = ?",
        tuple(params),
    )
    conn.commit()


def clear_progress(conn, comic_uuid: str) -> None:
    """Reset current_page, last_read_at, is_completed for comic. No-op if no metadata row."""
    comic_id = get_comic_id_by_uuid(conn, comic_uuid)
    if not comic_id:
        return
    cur = conn.execute("SELECT 1 FROM metadata WHERE comic_id = ?", (comic_id,))
    if not cur.fetchone():
        return
    conn.execute(
        "UPDATE metadata SET current_page = 0, last_read_at = NULL, is_completed = 0 WHERE comic_id = ?",
        (comic_id,),
    )
    conn.commit()
