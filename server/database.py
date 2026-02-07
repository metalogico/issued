"""Database connection and session management using SQLModel."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Iterator

from sqlmodel import SQLModel, create_engine, Session

from .config import DATA_DIR

DB_PATH = DATA_DIR / "library.db"
# Use SQLite with WAL mode enabled for concurrency
SQLITE_URL = f"sqlite:///{DB_PATH}"

# check_same_thread=False is needed for SQLite if using across threads (FastAPI)
engine = create_engine(SQLITE_URL, connect_args={"check_same_thread": False})


def get_session() -> Generator[Session, None, None]:
    """Dependency for FastAPI or context manager for scripts."""
    with Session(engine) as session:
        yield session


def init_db() -> None:
    """Create database tables."""
    # Import models to ensure they are registered with SQLModel.metadata
    from . import models  # noqa: F401

    # Enable WAL mode for better concurrency
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA journal_mode=WAL;")
        conn.exec_driver_sql("PRAGMA foreign_keys=ON;")

    SQLModel.metadata.create_all(engine)


def reset_database() -> None:
    """Delete the database file and recreate it."""
    if DB_PATH.exists():
        DB_PATH.unlink()
    init_db()


def get_engine():
    """Return the global engine instance."""
    return engine


def get_connection() -> sqlite3.Connection:
    """Return a sqlite3 connection with row factory for dict-like access."""
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


@contextmanager
def db_connection() -> Iterator[sqlite3.Connection]:
    """Context manager for sqlite3 connections. Auto-closes on exit."""
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()
