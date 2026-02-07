"""Alembic migration environment.

Imports the engine and metadata from the Issued server package so that
migrations use the exact same database connection the application does.
"""

from __future__ import annotations

from alembic import context
from sqlmodel import SQLModel

# Import engine (resolves PROJECT_ROOT → library.db automatically).
from server.database import engine  # noqa: F401

# Import all model modules so that their tables are registered on
# SQLModel.metadata before Alembic inspects it.
from server import models as _models  # noqa: F401

target_metadata = SQLModel.metadata


def run_migrations_online() -> None:
    """Run migrations with a real database connection."""
    with engine.connect() as conn:
        context.configure(
            connection=conn,
            target_metadata=target_metadata,
            # SQLite does not support transactional DDL in the same way
            # as PostgreSQL; keep transaction_per_migration=False (default)
            # to avoid surprises.
        )

        with context.begin_transaction():
            context.run_migrations()


# Alembic calls run_migrations_online or run_migrations_offline depending
# on --sql flag.  We only support online mode.
if context.is_offline_mode():
    raise RuntimeError(
        "Offline migration mode is not supported. "
        "Run without --sql."
    )
else:
    run_migrations_online()
