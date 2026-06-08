"""Reading progress queries for the web reader."""

from __future__ import annotations

from datetime import datetime, timezone

from .metadata import ensure_metadata_row, get_comic_id_by_uuid


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
    cur = conn.execute(
        "SELECT id FROM comics WHERE folder_id = ?",
        (folder_id,),
    )
    comic_ids = [row["id"] for row in cur.fetchall()]

    if not comic_ids:
        return 0

    for comic_id in comic_ids:
        ensure_metadata_row(conn, comic_id)

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
