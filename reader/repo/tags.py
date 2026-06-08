"""Tag queries for the web reader."""

from __future__ import annotations

from .comics import _COMICS_WITH_META
from .metadata import get_comic_id_by_uuid


def get_tags_for_comic(conn, comic_uuid: str) -> list[str]:
    """Sorted list of tag names for a comic."""
    comic_id = get_comic_id_by_uuid(conn, comic_uuid)
    if not comic_id:
        return []
    cur = conn.execute(
        """
        SELECT t.name FROM tags t
        INNER JOIN comic_tags ct ON ct.tag_id = t.id
        WHERE ct.comic_id = ?
        ORDER BY t.name COLLATE NOCASE
        """,
        (comic_id,),
    )
    return [row["name"] for row in cur.fetchall()]


def get_all_tags(conn) -> list[str]:
    """All tag names sorted (for autocomplete)."""
    cur = conn.execute("SELECT name FROM tags ORDER BY name COLLATE NOCASE")
    return [row["name"] for row in cur.fetchall()]


def get_all_tags_with_counts(conn) -> list[dict]:
    """All tags with their comic counts, sorted by name."""
    cur = conn.execute(
        """
        SELECT t.name, COUNT(ct.comic_id) AS comic_count
        FROM tags t
        LEFT JOIN comic_tags ct ON ct.tag_id = t.id
        GROUP BY t.id
        ORDER BY t.name COLLATE NOCASE
        """
    )
    return [dict(row) for row in cur.fetchall()]


def get_comics_for_tag(conn, tag_name: str) -> list[dict]:
    """All comics with the given tag, grouped by folder."""
    cur = conn.execute(
        _COMICS_WITH_META
        + """
         INNER JOIN comic_tags ct ON ct.comic_id = c.id
         INNER JOIN tags t ON t.id = ct.tag_id
        """
        + " WHERE t.name = ? ORDER BY f.name, c.filename",
        (tag_name,),
    )
    rows = [dict(row) for row in cur.fetchall()]
    groups: dict[str, list] = {}
    for row in rows:
        key = row["folder_name"] or ""
        groups.setdefault(key, [])
        groups[key].append(row)
    return [{"series": name, "comics": comics} for name, comics in groups.items()]


def delete_tag(conn, tag_name: str) -> bool:
    """Delete a tag and all its comic associations.  Returns True if it existed."""
    cur = conn.execute("SELECT id FROM tags WHERE name = ?", (tag_name,))
    row = cur.fetchone()
    if not row:
        return False
    conn.execute("DELETE FROM comic_tags WHERE tag_id = ?", (row["id"],))
    conn.execute("DELETE FROM tags WHERE id = ?", (row["id"],))
    conn.commit()
    return True


def set_tags_for_comic(conn, comic_uuid: str, tags: list[str]) -> list[str]:
    """Replace all tags for a comic.  Returns the final sorted tag list."""
    comic_id = get_comic_id_by_uuid(conn, comic_uuid)
    if not comic_id:
        return []

    normalised = sorted({t.strip() for t in tags if t.strip()}, key=str.casefold)

    tag_ids: list[int] = []
    for name in normalised:
        conn.execute(
            "INSERT INTO tags (name) VALUES (?) ON CONFLICT(name) DO NOTHING",
            (name,),
        )
        cur = conn.execute("SELECT id FROM tags WHERE name = ?", (name,))
        tag_ids.append(cur.fetchone()["id"])

    conn.execute("DELETE FROM comic_tags WHERE comic_id = ?", (comic_id,))
    for tag_id in tag_ids:
        conn.execute(
            "INSERT INTO comic_tags (comic_id, tag_id) VALUES (?, ?)",
            (comic_id, tag_id),
        )
    conn.commit()
    return normalised
