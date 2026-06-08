"""Tags and comic_tags tables

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-08
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | None = None
depends_on: str | None = None


def _table_exists(name: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(
        sa.text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:n"),
        {"n": name},
    )
    return result.fetchone() is not None


def upgrade() -> None:
    if not _table_exists("tags"):
        op.create_table(
            "tags",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(), nullable=False, unique=True),
        )
        op.create_index("ix_tags_name", "tags", ["name"], unique=True)

    if not _table_exists("comic_tags"):
        op.create_table(
            "comic_tags",
            sa.Column(
                "comic_id",
                sa.Integer(),
                sa.ForeignKey("comics.id", ondelete="CASCADE"),
                primary_key=True,
                nullable=False,
            ),
            sa.Column(
                "tag_id",
                sa.Integer(),
                sa.ForeignKey("tags.id", ondelete="CASCADE"),
                primary_key=True,
                nullable=False,
            ),
        )


def downgrade() -> None:
    if _table_exists("comic_tags"):
        op.drop_table("comic_tags")
    if _table_exists("tags"):
        op.drop_table("tags")
