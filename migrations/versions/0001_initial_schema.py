"""Initial schema: folders, comics, metadata

Revision ID: 0001
Revises: None
Create Date: 2025-01-01 00:00:00
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def _table_exists(name: str) -> bool:
    """Check whether a table already exists in the database."""
    conn = op.get_bind()
    result = conn.execute(
        sa.text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:n"),
        {"n": name},
    )
    return result.fetchone() is not None


def upgrade() -> None:
    # Every CREATE is guarded by _table_exists so that the migration is
    # safe to run against a DB that was originally created by the old
    # SQLModel.metadata.create_all() path (legacy stamp scenario).

    if not _table_exists("folders"):
        op.create_table(
            "folders",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("path", sa.String(), unique=True, nullable=False),
            sa.Column("parent_id", sa.Integer(), sa.ForeignKey("folders.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_folders_path", "folders", ["path"], unique=True)

    if not _table_exists("comics"):
        op.create_table(
            "comics",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("uuid", sa.String(), unique=True, nullable=False),
            sa.Column("filename", sa.String(), nullable=False),
            sa.Column("path", sa.String(), unique=True, nullable=False),
            sa.Column("format", sa.String(), nullable=False),
            sa.Column("file_size", sa.Integer(), nullable=False),
            sa.Column("page_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("file_modified_at", sa.DateTime(), nullable=False),
            sa.Column("last_scanned_at", sa.DateTime(), nullable=True),
            sa.Column("thumbnail_generated", sa.Boolean(), nullable=False, server_default="0"),
            sa.Column("folder_id", sa.Integer(), sa.ForeignKey("folders.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_comics_uuid", "comics", ["uuid"], unique=True)
        op.create_index("ix_comics_path", "comics", ["path"], unique=True)

    if not _table_exists("metadata"):
        op.create_table(
            "metadata",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("comic_id", sa.Integer(), sa.ForeignKey("comics.id"), unique=True, nullable=False),
            sa.Column("title", sa.String(), nullable=True),
            sa.Column("series", sa.String(), nullable=True),
            sa.Column("issue_number", sa.Integer(), nullable=True),
            sa.Column("publisher", sa.String(), nullable=True),
            sa.Column("year", sa.Integer(), nullable=True),
            sa.Column("month", sa.Integer(), nullable=True),
            sa.Column("writer", sa.String(), nullable=True),
            sa.Column("penciller", sa.String(), nullable=True),
            sa.Column("artist", sa.String(), nullable=True),
            sa.Column("summary", sa.String(), nullable=True),
            sa.Column("notes", sa.String(), nullable=True),
            sa.Column("web", sa.String(), nullable=True),
            sa.Column("language_iso", sa.String(), nullable=True),
            sa.Column("genre", sa.String(), nullable=True),
            sa.Column("score", sa.Integer(), nullable=True),
            sa.Column("is_completed", sa.Boolean(), nullable=False, server_default="0"),
            sa.Column("current_page", sa.Integer(), nullable=True),
            sa.Column("last_read_at", sa.DateTime(), nullable=True),
        )


def downgrade() -> None:
    # Reverse FK order: metadata → comics → folders.
    op.drop_table("metadata")
    op.drop_table("comics")
    op.drop_table("folders")
