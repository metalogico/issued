"""Migration 0004 must run before anything scans an existing database."""

from __future__ import annotations

import os
import sqlite3

import pytest
from alembic import command as alembic_command
from sqlmodel import create_engine

from server import migrations, scanner
from server.database import init_db
from tests.test_scanner import _create_minimal_cbz, _make_config


@pytest.fixture
def db_file(tmp_path, monkeypatch):
    db_file = tmp_path / "library.db"
    monkeypatch.setattr("server.database.DB_PATH", db_file, raising=True)
    monkeypatch.setattr("server.migrations.DB_PATH", db_file, raising=True)
    monkeypatch.setattr(
        "server.database.engine",
        create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False}),
        raising=True,
    )
    return db_file


def _old_to_relative(absolute_path, library_root):
    """``to_relative`` before revision 0004: OS-native separators."""
    try:
        return str(absolute_path.relative_to(library_root))
    except ValueError:
        return str(absolute_path)


def _comics(db_file):
    conn = sqlite3.connect(db_file)
    try:
        return sorted(conn.execute("SELECT uuid, path FROM comics").fetchall())
    finally:
        conn.close()


def test_legacy_database_is_stamped_below_the_data_migrations(db_file):
    init_db()                           # tables, but no alembic_version: a legacy DB

    migrations.stamp_if_needed()

    assert migrations.get_status() == (migrations.LEGACY_BASELINE, "0004")


@pytest.mark.skipif(os.name != "nt", reason="backslash separators only exist in Windows databases")
@pytest.mark.parametrize("stamped_at", ["0003", None], ids=["at-0003", "legacy"])
def test_scan_command_converts_a_windows_database_without_duplicates(
    tmp_path, monkeypatch, db_file, stamped_at
):
    lib = tmp_path / "lib"
    (lib / "Marvel" / "XMen").mkdir(parents=True)
    _create_minimal_cbz(lib / "Marvel" / "XMen" / "issue01.cbz")
    config = _make_config(lib)

    with monkeypatch.context() as old_version:
        for module in ("server.path_utils", "server.repository", "server.scanner"):
            old_version.setattr(f"{module}.to_relative", _old_to_relative, raising=False)
        scanner.scan_library(config, path=None, force=True)
    if stamped_at:
        alembic_command.stamp(migrations._alembic_cfg(), stamped_at)
    before = _comics(db_file)
    assert [path for _, path in before] == ["Marvel\\XMen\\issue01.cbz"]

    monkeypatch.setattr("main.setup_logging", lambda: None)
    monkeypatch.setattr("main._ensure_config", lambda: config)
    monkeypatch.setattr("main.typer.echo", lambda *a, **k: None)
    from main import scan

    scan(force=False, path=None, prune=False)

    assert _comics(db_file) == [(before[0][0], "Marvel/XMen/issue01.cbz")]
