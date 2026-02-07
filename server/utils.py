"""Utility functions for Issued."""

from __future__ import annotations

from pathlib import Path

from .logging_config import get_logger

logger = get_logger(__name__)


# ANSI color codes
class Colors:
    """ANSI color codes for terminal output."""
    RESET = "\033[0m"
    DIM = "\033[2m"
    GRAY = "\033[90m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"


def short_path(path: Path) -> str:
    """Return abbreviated path showing only parent folder + filename.
    
    Example: /very/long/path/to/folder/file.cbz -> folder/file.cbz
    """
    return f"{path.parent.name}/{path.name}"


def dim_log(message: str) -> str:
    """Return message with dim/gray ANSI color."""
    return f"{Colors.GRAY}{message}{Colors.RESET}"


def error_log(message: str) -> str:
    """Return message with red ANSI color."""
    return f"{Colors.RED}{message}{Colors.RESET}"


def delete_thumbnails(comic_uuids: list[str], thumbnails_dir: Path) -> int:
    """Delete thumbnail files for given comic UUIDs.

    Returns count of deleted thumbnails.
    """
    deleted = 0
    for comic_uuid in comic_uuids:
        thumb_path = thumbnails_dir / f"{comic_uuid}.jpg"
        if thumb_path.exists():
            try:
                thumb_path.unlink()
                deleted += 1
            except Exception as exc:
                logger.error(f"Failed to delete thumbnail {thumb_path}: {exc}")
    return deleted
