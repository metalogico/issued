"""Ongoing series marks per folder

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
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
    if not _table_exists("ongoing_series"):
        op.create_table(
            "ongoing_series",
            sa.Column(
                "folder_id",
                sa.Integer(),
                sa.ForeignKey("folders.id", ondelete="CASCADE"),
                primary_key=True,
                nullable=False,
            ),
            sa.Column("marked_at", sa.DateTime(), nullable=False),
        )


def downgrade() -> None:
    if _table_exists("ongoing_series"):
        op.drop_table("ongoing_series")
