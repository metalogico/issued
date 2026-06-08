"""Ongoing series queries for the web reader."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from ..gaps import issue_gaps


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
    def _issue_from_filename(filename: str | None) -> int | None:
        if not filename:
            return None
        stem = filename.rsplit(".", 1)[0]
        # Remove explicit year groups, e.g. "(2025)", so they are never treated as issue numbers.
        stem = re.sub(r"\(\s*\d{4}\s*\)", "", stem)
        matches = re.findall(r"\d+", stem)
        if not matches:
            return None
        filtered = [
            token
            for token in matches
            if not (len(token) == 4 and 1900 <= int(token) <= 2100)
        ]
        if not filtered:
            filtered = matches
        # Prefer likely issue tokens: zero-padded or 3+ digits, then earliest token in filename.
        for token in filtered:
            if len(token) >= 3 or (len(token) > 1 and token.startswith("0")):
                return int(token)
        return int(filtered[0])

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

    # Last added comic per folder (by created_at, then id)
    cur = conn.execute(
        f"""
        WITH ranked AS (
            SELECT c.folder_id, c.uuid, c.filename,
                   m.issue_number, m.year, m.month,
                   ROW_NUMBER() OVER (
                       PARTITION BY c.folder_id
                       ORDER BY c.created_at DESC, c.id DESC
                   ) AS rn
            FROM comics c
            LEFT JOIN metadata m ON m.comic_id = c.id
            WHERE c.folder_id IN ({placeholders})
        )
        SELECT folder_id, uuid, filename, issue_number, year, month
        FROM ranked
        WHERE rn = 1
        """,
        folder_ids,
    )
    last_by_folder: dict[int, dict] = {}
    for row in cur.fetchall():
        last_by_folder[row["folder_id"]] = dict(row)

    # Issue numbers per folder (filename-first, metadata fallback)
    cur = conn.execute(
        f"""
        SELECT c.folder_id,
               c.uuid,
               c.filename,
               m.issue_number
        FROM comics c
        LEFT JOIN metadata m ON m.comic_id = c.id
        WHERE c.folder_id IN ({placeholders})
        """,
        folder_ids,
    )
    issues_by_folder: dict[int, list[int]] = {fid: [] for fid in folder_ids}
    nulls_by_folder: dict[int, int] = {fid: 0 for fid in folder_ids}
    max_issue_by_folder: dict[int, int] = {}
    max_issue_uuid_by_folder: dict[int, str] = {}
    for row in cur.fetchall():
        fid = row["folder_id"]
        parsed = _issue_from_filename(row["filename"])
        # Prefer filename issue extraction; use metadata only when filename is ambiguous.
        num = parsed if parsed is not None else (
            int(row["issue_number"]) if row["issue_number"] is not None else None
        )
        if num is None:
            nulls_by_folder[fid] = nulls_by_folder.get(fid, 0) + 1
            continue
        issues_by_folder[fid].append(num)
        if fid not in max_issue_by_folder or num > max_issue_by_folder[fid]:
            max_issue_by_folder[fid] = num
            max_issue_uuid_by_folder[fid] = row["uuid"]

    # Max created_at for sort (most recently added series first)
    cur = conn.execute(
        f"""
        SELECT folder_id, MAX(created_at) AS max_ts
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
        last_issue_number = max_issue_by_folder.get(fid)
        last = last_by_folder.get(fid, {})
        last_issue_uuid = max_issue_uuid_by_folder.get(fid)
        last_added_issue_number = _issue_from_filename(last.get("filename"))
        if last_added_issue_number is None and last.get("issue_number") is not None:
            last_added_issue_number = int(last["issue_number"])
        out.append(
            {
                "folder_id": fid,
                "folder_name": r["folder_name"],
                "marked_at": r["marked_at"],
                "issue_count": counts.get(fid, 0),
                "last_comic_uuid": last.get("uuid"),
                "last_issue_number": last_issue_number,
                "last_issue_uuid": last_issue_uuid,
                "last_added_issue_number": last_added_issue_number,
                "last_cover_year": last.get("year"),
                "last_cover_month": last.get("month"),
                "last_added_at": max_ts_by_folder.get(fid),
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
