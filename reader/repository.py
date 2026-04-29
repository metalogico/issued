"""Data access layer for the web reader: all DB queries in one place."""

from __future__ import annotations

from datetime import datetime, timezone

from .gaps import issue_gaps

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
    SELECT c.uuid, c.filename, c.page_count,
           (m.is_completed = 1) AS is_completed,
           m.title, m.publisher, m.year, m.artist, m.writer, m.penciller,
           m.score, m.last_read_at,
           f.name AS folder_name
    FROM comics c
    LEFT JOIN metadata m ON m.comic_id = c.id
    LEFT JOIN folders f ON f.id = c.folder_id
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


def search_comics_grouped(conn, q: str) -> list[dict]:
    """Comics matching q grouped by parent folder (series), ordered by folder name then filename."""
    if not q or not q.strip():
        return []
    like = f"%{q.strip()}%"
    cur = conn.execute(
        _COMICS_WITH_META
        + " WHERE c.filename LIKE ? OR m.title LIKE ? OR m.series LIKE ?"
        + " ORDER BY f.name, c.filename",
        (like, like, like),
    )
    rows = [dict(row) for row in cur.fetchall()]
    groups: dict[str, list] = {}
    for row in rows:
        key = row["folder_name"] or ""
        groups.setdefault(key, [])
        groups[key].append(row)
    return [{"series": name, "comics": comics} for name, comics in groups.items()]


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
        "UPDATE metadata SET current_page = NULL, last_read_at = NULL, is_completed = 0 WHERE comic_id = ?",
        (comic_id,),
    )
    conn.commit()


def mark_all_comics_in_folder_completed(conn, folder_id: int) -> int:
    """Mark all comics in a folder as completed. Returns number of comics updated."""
    # Get all comic IDs in the folder
    cur = conn.execute(
        "SELECT id FROM comics WHERE folder_id = ?",
        (folder_id,),
    )
    comic_ids = [row["id"] for row in cur.fetchall()]
    
    if not comic_ids:
        return 0
    
    # Ensure metadata rows exist for all comics
    for comic_id in comic_ids:
        ensure_metadata_row(conn, comic_id)
    
    # Mark all as completed
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        """UPDATE metadata 
           SET is_completed = 1, last_read_at = ? 
           WHERE comic_id IN ({})""".format(",".join("?" * len(comic_ids))),
        [now] + comic_ids,
    )
    conn.commit()
    
    return cur.rowcount


def toggle_comic_completed(conn, comic_uuid: str) -> bool | None:
    """Toggle is_completed for a comic and return the new state, or None if comic not found."""
    comic_id = get_comic_id_by_uuid(conn, comic_uuid)
    if not comic_id:
        return None

    ensure_metadata_row(conn, comic_id)
    cur = conn.execute(
        "SELECT is_completed FROM metadata WHERE comic_id = ?",
        (comic_id,),
    )
    row = cur.fetchone()
    current_state = bool(row["is_completed"]) if row and row["is_completed"] is not None else False
    new_state = not current_state

    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE metadata SET is_completed = ?, last_read_at = ? WHERE comic_id = ?",
        (1 if new_state else 0, now, comic_id),
    )
    conn.commit()

    return new_state


# --- Ongoing series (folder marks) ---


def folder_is_leaf(conn, folder_id: int) -> bool:
    """True if folder has no child folders (series folder in scanner terms)."""
    cur = conn.execute(
        "SELECT COUNT(*) AS c FROM folders WHERE parent_id = ?",
        (folder_id,),
    )
    return int(cur.fetchone()["c"]) == 0


def folder_comic_count(conn, folder_id: int) -> int:
    cur = conn.execute(
        "SELECT COUNT(*) AS c FROM comics WHERE folder_id = ?",
        (folder_id,),
    )
    return int(cur.fetchone()["c"])


def is_ongoing_series(conn, folder_id: int) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM ongoing_series WHERE folder_id = ?",
        (folder_id,),
    )
    return cur.fetchone() is not None


def set_ongoing_series(conn, folder_id: int, ongoing: bool) -> None:
    """Insert or remove ongoing mark. Caller should commit."""
    if ongoing:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            INSERT INTO ongoing_series (folder_id, marked_at) VALUES (?, ?)
            ON CONFLICT(folder_id) DO UPDATE SET marked_at = excluded.marked_at
            """,
            (folder_id, now),
        )
    else:
        conn.execute(
            "DELETE FROM ongoing_series WHERE folder_id = ?",
            (folder_id,),
        )
    conn.commit()


def list_ongoing_series_rows(conn) -> list[dict]:
    """Rows for ongoing list page: counts, last added issue, gap info."""
    cur = conn.execute(
        """
        SELECT os.folder_id, f.name AS folder_name,
               os.marked_at
        FROM ongoing_series os
        INNER JOIN folders f ON f.id = os.folder_id
        ORDER BY f.name COLLATE NOCASE
        """
    )
    base_rows = [dict(row) for row in cur.fetchall()]
    if not base_rows:
        return []

    folder_ids = [r["folder_id"] for r in base_rows]
    placeholders = ",".join("?" * len(folder_ids))

    # Issue counts per folder
    cur = conn.execute(
        f"""
        SELECT folder_id, COUNT(*) AS issue_count
        FROM comics
        WHERE folder_id IN ({placeholders})
        GROUP BY folder_id
        """,
        folder_ids,
    )
    counts = {row["folder_id"]: int(row["issue_count"]) for row in cur.fetchall()}

    # Last added comic per folder (by scan time, then id)
    cur = conn.execute(
        f"""
        WITH ranked AS (
            SELECT c.folder_id, c.uuid,
                   m.issue_number, m.year, m.month,
                   COALESCE(c.last_scanned_at, c.created_at) AS sort_ts,
                   ROW_NUMBER() OVER (
                       PARTITION BY c.folder_id
                       ORDER BY COALESCE(c.last_scanned_at, c.created_at) DESC, c.id DESC
                   ) AS rn
            FROM comics c
            LEFT JOIN metadata m ON m.comic_id = c.id
            WHERE c.folder_id IN ({placeholders})
        )
        SELECT folder_id, uuid, issue_number, year, month
        FROM ranked
        WHERE rn = 1
        """,
        folder_ids,
    )
    last_by_folder: dict[int, dict] = {}
    for row in cur.fetchall():
        last_by_folder[row["folder_id"]] = dict(row)

    # Distinct issue numbers + null counts per folder
    cur = conn.execute(
        f"""
        SELECT c.folder_id,
               m.issue_number,
               COUNT(*) AS row_count
        FROM comics c
        LEFT JOIN metadata m ON m.comic_id = c.id
        WHERE c.folder_id IN ({placeholders})
        GROUP BY c.folder_id, m.issue_number
        """,
        folder_ids,
    )
    issues_by_folder: dict[int, list[int]] = {fid: [] for fid in folder_ids}
    nulls_by_folder: dict[int, int] = {fid: 0 for fid in folder_ids}
    for row in cur.fetchall():
        fid = row["folder_id"]
        num = row["issue_number"]
        cnt = int(row["row_count"])
        if num is None:
            nulls_by_folder[fid] = nulls_by_folder.get(fid, 0) + cnt
        else:
            for _ in range(cnt):
                issues_by_folder[fid].append(int(num))

    # Max last_scanned for sort (most recently updated series first)
    cur = conn.execute(
        f"""
        SELECT folder_id, MAX(COALESCE(last_scanned_at, created_at)) AS max_ts
        FROM comics
        WHERE folder_id IN ({placeholders})
        GROUP BY folder_id
        """,
        folder_ids,
    )
    max_ts_by_folder = {row["folder_id"]: row["max_ts"] for row in cur.fetchall()}

    out: list[dict] = []
    for r in base_rows:
        fid = r["folder_id"]
        nums = issues_by_folder.get(fid, [])
        gap_info = issue_gaps(nums)
        last = last_by_folder.get(fid, {})
        out.append(
            {
                "folder_id": fid,
                "folder_name": r["folder_name"],
                "marked_at": r["marked_at"],
                "issue_count": counts.get(fid, 0),
                "last_comic_uuid": last.get("uuid"),
                "last_issue_number": last.get("issue_number"),
                "last_cover_year": last.get("year"),
                "last_cover_month": last.get("month"),
                "missing_issues": gap_info["missing"],
                "has_numbered_issues": gap_info["has_numbered_issues"],
                "has_null_issue_numbers": nulls_by_folder.get(fid, 0) > 0,
                "_sort_ts": max_ts_by_folder.get(fid),
            }
        )

    out.sort(
        key=lambda x: (
            x["_sort_ts"] or "1970-01-01T00:00:00+00:00",
            x["folder_name"].lower(),
        ),
        reverse=True,
    )
    for row in out:
        row.pop("_sort_ts", None)
    return out
