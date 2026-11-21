"""Store relative paths with forward slashes

Before this revision, ``to_relative`` returned OS-native separators, so a
database built on Windows holds paths such as ``Marvel\\X-Men.cbz`` while the
repository's ``LIKE '<folder>/%'`` queries expect forward slashes.

Only Windows databases are rewritten: on POSIX a backslash is a legal
filename character, not a separator, and must be kept as is.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-08
"""

from __future__ import annotations

import os

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | None = None
depends_on: str | None = None

PATH_TABLES = ("folders", "comics")


def replace_separator(conn, old: str, new: str) -> None:
    for table in PATH_TABLES:
        conn.execute(
            sa.text(f"UPDATE {table} SET path = REPLACE(path, :old, :new) WHERE instr(path, :old) > 0"),
            {"old": old, "new": new},
        )


def upgrade() -> None:
    if os.name == "nt":
        replace_separator(op.get_bind(), "\\", "/")


def downgrade() -> None:
    if os.name == "nt":
        replace_separator(op.get_bind(), "/", "\\")
