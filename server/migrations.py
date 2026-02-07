"""Alembic migration helpers for Issued.

This is the only module in the project that imports alembic directly.
Everything else (CLI, serve) goes through the functions below.
"""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory

from .config import DATA_DIR, PROJECT_ROOT


# ---------------------------------------------------------------------------
# Alembic config object — reused by every public function
# ---------------------------------------------------------------------------

def _alembic_cfg() -> AlembicConfig:
    """Build an AlembicConfig that points at our alembic.ini."""
    ini_path = PROJECT_ROOT / "alembic.ini"
    cfg = AlembicConfig(str(ini_path))
    # Override script_location to an absolute path so it works regardless
    # of the current working directory.
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    return cfg


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

DB_PATH = DATA_DIR / "library.db"


def _backup_db() -> None:
    """Copy library.db → library.db.bak (overwrite previous backup)."""
    if DB_PATH.exists():
        shutil.copy2(DB_PATH, DB_PATH.with_suffix(".db.bak"))


def _alembic_version_exists() -> bool:
    """Return True when the alembic_version table is present in the DB."""
    if not DB_PATH.exists():
        return False
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='alembic_version'"
        )
        return cur.fetchone() is not None
    finally:
        conn.close()


def run_migrations(backup: bool = True) -> None:
    """Run ``alembic upgrade head``.

    If *backup* is True and library.db already exists, a copy is made first.
    """
    if backup:
        _backup_db()
    alembic_command.upgrade(_alembic_cfg(), "head")


def stamp_if_needed() -> None:
    """Stamp an existing (legacy) database to the current head.

    Called by ``serve`` on startup.  If the DB already has an
    alembic_version row this is a no-op.  If the DB exists but has no
    alembic_version table (i.e. it was created by the old
    ``create_all`` path), we stamp it to head so that future
    ``upgrade`` calls know the baseline.
    """
    if not DB_PATH.exists():
        return                          # nothing to stamp; init_db will create it
    if _alembic_version_exists():
        return                          # already managed
    # Legacy DB — tables exist but no version info.  Stamp without running
    # any migration SQL (tables are already there).
    alembic_command.stamp(_alembic_cfg(), "head")


def get_status() -> tuple[str | None, str]:
    """Return (current_revision, head_revision).

    current_revision is None when the DB does not exist or has never
    been stamped/migrated.
    """
    cfg = _alembic_cfg()

    # Head is a static property of the migration scripts — no DB needed.
    script = ScriptDirectory.from_config(cfg)
    head_rev: str = script.get_current_head() or "unknown"

    # Current requires reading the DB.
    if not DB_PATH.exists() or not _alembic_version_exists():
        return None, head_rev

    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.execute("SELECT version_num FROM alembic_version")
        row = cur.fetchone()
        return (row[0] if row else None), head_rev
    finally:
        conn.close()
