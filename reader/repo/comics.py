"""Comic list queries for the web reader."""

from __future__ import annotations


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
    """Comics matching q in filename/title/series/tags, with is_completed."""
    if not q or not q.strip():
        return []
    like = f"%{q.strip()}%"
    cur = conn.execute(
        _COMICS_WITH_META
        + """
         LEFT JOIN comic_tags ct ON ct.comic_id = c.id
         LEFT JOIN tags t ON t.id = ct.tag_id
        """
        + " WHERE c.filename LIKE ? OR m.title LIKE ? OR m.series LIKE ? OR t.name LIKE ?"
        + " GROUP BY c.id ORDER BY c.filename",
        (like, like, like, like),
    )
    return [dict(row) for row in cur.fetchall()]


def search_comics_grouped(conn, q: str) -> list[dict]:
    """Comics matching q grouped by parent folder (series), ordered by folder name then filename."""
    if not q or not q.strip():
        return []
    like = f"%{q.strip()}%"
    cur = conn.execute(
        _COMICS_WITH_META
        + """
         LEFT JOIN comic_tags ct ON ct.comic_id = c.id
         LEFT JOIN tags t ON t.id = ct.tag_id
        """
        + " WHERE c.filename LIKE ? OR m.title LIKE ? OR m.series LIKE ? OR t.name LIKE ?"
        + " GROUP BY c.id ORDER BY f.name, c.filename",
        (like, like, like, like),
    )
    rows = [dict(row) for row in cur.fetchall()]
    groups: dict[str, list] = {}
    for row in rows:
        key = row["folder_name"] or ""
        groups.setdefault(key, [])
        groups[key].append(row)
    return [{"series": name, "comics": comics} for name, comics in groups.items()]
