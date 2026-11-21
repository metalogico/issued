from __future__ import annotations

import importlib.util
from pathlib import Path, PureWindowsPath

from sqlalchemy import create_engine, text

from server.path_utils import to_relative

PROJECT_ROOT = Path(__file__).parent.parent


def _load_migration(name: str):
    path = PROJECT_ROOT / "migrations" / "versions" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_to_relative_uses_forward_slashes_for_windows_paths():
    root = PureWindowsPath("C:/Comics")

    assert to_relative(root / "Marvel" / "XMen" / "issue01.cbz", root) == "Marvel/XMen/issue01.cbz"
    assert to_relative(root, root) == "."


def test_posix_paths_migration_rewrites_backslash_separators():
    migration = _load_migration("0004_posix_paths")
    engine = create_engine("sqlite://")

    with engine.begin() as conn:
        for table in migration.PATH_TABLES:
            conn.execute(text(f"CREATE TABLE {table} (path TEXT)"))
            conn.execute(
                text(f"INSERT INTO {table} (path) VALUES ('.'), ('Marvel'), ('Marvel\\XMen\\issue01.cbz')")
            )

        migration.replace_separator(conn, "\\", "/")

        for table in migration.PATH_TABLES:
            paths = sorted(row[0] for row in conn.execute(text(f"SELECT path FROM {table}")))
            assert paths == [".", "Marvel", "Marvel/XMen/issue01.cbz"]
