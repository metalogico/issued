"""Folder queries for the web reader."""

from __future__ import annotations


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
