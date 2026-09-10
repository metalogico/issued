"""Series reading order and continuation rules.

The sequencing policy lives here so folders, reader navigation, and future reading
list contexts can share the same behavior. Feature 02 can replace the temporary
filename ordering without changing those callers.
"""

from __future__ import annotations

import re
from typing import Any

from . import repo


def _natural_key(value: str) -> tuple:
    """Return a deterministic, case-insensitive key where 2 sorts before 10."""
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part.casefold())
        for part in re.split(r"(\d+)", value)
        if part
    )


def _ordered(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda row: (_natural_key(row["filename"]), row["uuid"]))


def _issue_number(row: dict) -> int | None:
    """Best-effort integer issue number until the numbering feature owns parsing."""
    stem = row["filename"].rsplit(".", 1)[0]
    stem = re.sub(r"\(\s*(?:19|20|21)\d{2}\s*\)", "", stem)
    matches = re.findall(r"(?<![\d.])#?0*(\d+)(?![\d.])", stem)
    if len(matches) == 1:
        return int(matches[0])
    metadata_number = row.get("issue_number")
    return int(metadata_number) if metadata_number is not None else None


def _comic_summary(row: dict | None) -> dict | None:
    if row is None:
        return None
    return {
        "uuid": row["uuid"],
        "filename": row["filename"],
        "title": row.get("title"),
        "issue_number": _issue_number(row),
        "is_completed": bool(row.get("is_completed")),
    }


def _missing_between(current: dict, following: dict | None) -> list[int]:
    if following is None:
        return []
    current_number = _issue_number(current)
    following_number = _issue_number(following)
    if current_number is None or following_number is None:
        return []
    if following_number <= current_number + 1:
        return []
    return list(range(current_number + 1, following_number))


def get_continue_series(conn, folder_id: int) -> dict[str, Any]:
    """Return the comic a Continue series action should open."""
    comics = _ordered(repo.get_series_comics(conn, folder_id))
    if not comics:
        return {"status": "empty", "target": None, "resume": False}

    incomplete = [comic for comic in comics if not bool(comic.get("is_completed"))]
    if not incomplete:
        return {"status": "all_read", "target": None, "resume": False}

    started = [
        comic
        for comic in incomplete
        if comic.get("current_page") is not None
        and comic.get("last_read_at") is not None
        and int(comic["current_page"]) < int(comic.get("page_count") or 1)
    ]
    if started:
        target = max(
            started,
            key=lambda comic: (str(comic.get("last_read_at") or ""), comic["uuid"]),
        )
        resume = True
    else:
        target = incomplete[0]
        resume = False

    return {"status": "ready", "target": _comic_summary(target), "resume": resume}


def get_series_navigation(conn, comic_uuid: str) -> dict[str, Any] | None:
    """Return previous/next issue context for a comic's direct parent folder."""
    result = repo.get_series_comics_for_comic(conn, comic_uuid)
    if result is None:
        return None
    folder_id, rows = result
    comics = _ordered(rows)
    try:
        index = next(i for i, comic in enumerate(comics) if comic["uuid"] == comic_uuid)
    except StopIteration:
        return None

    current = comics[index]
    previous = comics[index - 1] if index > 0 else None
    following = comics[index + 1] if index + 1 < len(comics) else None
    return {
        "context": "series",
        "folder_id": folder_id,
        "position": index + 1,
        "total": len(comics),
        "previous": _comic_summary(previous),
        "next": _comic_summary(following),
        "missing_issues_to_next": _missing_between(current, following),
    }
