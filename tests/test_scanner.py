import io
import sqlite3
import zipfile
from pathlib import Path

import pytest
from PIL import Image
from sqlmodel import create_engine

from server.config import IssuedConfig, LibraryConfig, MonitoringConfig, ReaderAuthConfig, ScannerConfig, ServerConfig, ThumbnailConfig
from server.database import DB_PATH, get_connection, init_db
from server import scanner
from server.scanner import LibraryUnavailableError


def _create_minimal_cbz(path: Path) -> None:
    """Create a valid CBZ file with a tiny PNG image."""
    img = Image.new("RGB", (10, 10), color="red")
    img_bytes = io.BytesIO()
    img.save(img_bytes, format="PNG")
    img_bytes.seek(0)

    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("page001.png", img_bytes.read())


def _make_config(tmp_library: Path) -> IssuedConfig:
    return IssuedConfig(
        library=LibraryConfig(path=tmp_library, name="Test Library"),
        server=ServerConfig(),
        thumbnails=ThumbnailConfig(),
        scanner=ScannerConfig(),
        monitoring=MonitoringConfig(),
        reader_auth=ReaderAuthConfig(),
    )


def _patch_db(tmp_path, monkeypatch):
    db_file = tmp_path / "library.db"
    monkeypatch.setattr("server.database.DB_PATH", db_file, raising=True)
    monkeypatch.setattr(
        "server.database.engine",
        create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False}),
        raising=True,
    )
    return db_file


def _create_minimal_cbz(path: Path) -> None:
    """Create a valid CBZ file with a tiny PNG image."""
    img = Image.new("RGB", (10, 10), color="red")
    img_bytes = io.BytesIO()
    img.save(img_bytes, format="PNG")
    img_bytes.seek(0)

    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("page001.png", img_bytes.read())


def _make_config(tmp_library: Path) -> IssuedConfig:
    return IssuedConfig(
        library=LibraryConfig(path=tmp_library, name="Test Library"),
        server=ServerConfig(),
        thumbnails=ThumbnailConfig(),
        scanner=ScannerConfig(),
        monitoring=MonitoringConfig(),
        reader_auth=ReaderAuthConfig(),
    )


def test_init_db_creates_schema(tmp_path, monkeypatch):
    # Point DB_PATH and engine to a temp file
    db_file = tmp_path / "library.db"
    monkeypatch.setattr("server.database.DB_PATH", db_file, raising=True)
    from sqlmodel import create_engine
    monkeypatch.setattr(
        "server.database.engine",
        create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False}),
        raising=True,
    )

    init_db()
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        table_names = {row[0] for row in cur.fetchall()}
        assert "folders" in table_names
        assert "comics" in table_names
        assert "metadata" in table_names
    finally:
        conn.close()


def test_scan_library_smoke(tmp_path, monkeypatch):
    # Create fake library structure
    lib = tmp_path / "lib"
    lib.mkdir()
    series_dir = lib / "Series"
    series_dir.mkdir()
    comic_file = series_dir / "issue01.cbz"
    _create_minimal_cbz(comic_file)

    db_file = tmp_path / "library.db"
    monkeypatch.setattr("server.database.DB_PATH", db_file, raising=True)
    from sqlmodel import create_engine
    monkeypatch.setattr(
        "server.database.engine",
        create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False}),
        raising=True,
    )

    config = _make_config(lib)
    scanner.scan_library(config, path=None, force=True)

    conn = sqlite3.connect(db_file)
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.execute("SELECT path FROM folders")
        folder_paths = {row["path"] for row in cur.fetchall()}
        # Paths are stored relative to library root
        assert "." in folder_paths
        assert "Series" in folder_paths

        cur = conn.execute("SELECT path FROM comics")
        comic_paths = {row["path"] for row in cur.fetchall()}
        assert "Series/issue01.cbz" in comic_paths
    finally:
        conn.close()


def test_scan_library_inserts_comics_in_natural_order(tmp_path, monkeypatch):
    lib = tmp_path / "lib"
    lib.mkdir()
    series_dir = lib / "Series"
    series_dir.mkdir()

    # Create files in a non-natural order to verify scan ordering behavior.
    for filename in ("issue10.cbz", "issue2.cbz", "issue1.cbz"):
        _create_minimal_cbz(series_dir / filename)

    db_file = tmp_path / "library.db"
    monkeypatch.setattr("server.database.DB_PATH", db_file, raising=True)
    from sqlmodel import create_engine

    monkeypatch.setattr(
        "server.database.engine",
        create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False}),
        raising=True,
    )

    config = _make_config(lib)
    scanner.scan_library(config, path=None, force=True)

    conn = sqlite3.connect(db_file)
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT filename FROM comics ORDER BY id").fetchall()
        assert [row["filename"] for row in rows] == [
            "issue1.cbz",
            "issue2.cbz",
            "issue10.cbz",
        ]
    finally:
        conn.close()


def test_library_is_ready_when_db_and_folder_are_empty(tmp_path, monkeypatch):
    lib = tmp_path / "lib"
    lib.mkdir()
    _patch_db(tmp_path, monkeypatch)

    assert scanner.library_is_ready(_make_config(lib)) is True


def test_library_is_ready_false_when_path_missing(tmp_path, monkeypatch):
    _patch_db(tmp_path, monkeypatch)
    missing = tmp_path / "no-such-library"
    assert scanner.library_is_ready(_make_config(missing)) is False


def test_library_is_ready_false_when_empty_mount_has_db_comics(tmp_path, monkeypatch):
    lib = tmp_path / "lib"
    lib.mkdir()
    series_dir = lib / "Series"
    series_dir.mkdir()
    _create_minimal_cbz(series_dir / "issue01.cbz")
    _patch_db(tmp_path, monkeypatch)

    config = _make_config(lib)
    scanner.scan_library(config, force=True)

    for comic in lib.rglob("*.cbz"):
        comic.unlink()

    assert scanner.library_is_ready(config) is False


def test_scan_refuses_empty_mount_and_keeps_database(tmp_path, monkeypatch):
    lib = tmp_path / "lib"
    lib.mkdir()
    series_dir = lib / "Series"
    series_dir.mkdir()
    _create_minimal_cbz(series_dir / "issue01.cbz")
    db_file = _patch_db(tmp_path, monkeypatch)

    config = _make_config(lib)
    scanner.scan_library(config, force=True)

    for comic in lib.rglob("*.cbz"):
        comic.unlink()

    with pytest.raises(LibraryUnavailableError, match="Database left untouched"):
        scanner.scan_library(config)

    conn = sqlite3.connect(db_file)
    try:
        count = conn.execute("SELECT COUNT(*) FROM comics").fetchone()[0]
        assert count == 1
        folders = {row[0] for row in conn.execute("SELECT path FROM folders")}
        assert "Series" in folders
    finally:
        conn.close()


def test_scan_prunes_single_missing_file_when_library_is_healthy(tmp_path, monkeypatch):
    lib = tmp_path / "lib"
    lib.mkdir()
    series_dir = lib / "Series"
    series_dir.mkdir()
    keep = series_dir / "keep.cbz"
    drop = series_dir / "drop.cbz"
    _create_minimal_cbz(keep)
    _create_minimal_cbz(drop)
    db_file = _patch_db(tmp_path, monkeypatch)

    config = _make_config(lib)
    scanner.scan_library(config, force=True)
    drop.unlink()

    stats = scanner.scan_library(config)
    assert stats["deleted"] == 1

    conn = sqlite3.connect(db_file)
    try:
        names = {row[0] for row in conn.execute("SELECT filename FROM comics")}
        assert names == {"keep.cbz"}
    finally:
        conn.close()


def test_scan_prune_deletes_comics_when_folder_is_empty(tmp_path, monkeypatch):
    lib = tmp_path / "lib"
    lib.mkdir()
    series_dir = lib / "Series"
    series_dir.mkdir()
    _create_minimal_cbz(series_dir / "issue01.cbz")
    db_file = _patch_db(tmp_path, monkeypatch)

    config = _make_config(lib)
    scanner.scan_library(config, force=True)
    for comic in lib.rglob("*.cbz"):
        comic.unlink()

    stats = scanner.scan_library(config, prune=True)
    assert stats["deleted"] == 1

    conn = sqlite3.connect(db_file)
    try:
        assert conn.execute("SELECT COUNT(*) FROM comics").fetchone()[0] == 0
    finally:
        conn.close()


def test_wait_for_library_returns_after_ready(tmp_path, monkeypatch):
    states = [False, False, True]
    monkeypatch.setattr(
        scanner,
        "library_is_ready",
        lambda cfg: states.pop(0) if states else True,
    )
    sleeps = []
    monkeypatch.setattr(scanner.time, "sleep", lambda seconds: sleeps.append(seconds))

    scanner.wait_for_library(_make_config(tmp_path / "lib"), interval=0.01)

    assert sleeps == [0.01, 0.01]


def test_serve_waits_before_scan_and_http(tmp_path, monkeypatch):
    order = []
    monkeypatch.setattr("main.wait_for_library", lambda cfg: order.append("wait"))
    monkeypatch.setattr(
        "main.scan_library",
        lambda cfg: order.append("scan")
        or {"added": 0, "updated": 0, "deleted": 0, "skipped": 0},
    )
    monkeypatch.setattr("main.run_server", lambda *a, **k: order.append("http"))
    monkeypatch.setattr("main.init_db", lambda: None)
    monkeypatch.setattr("main.stamp_if_needed", lambda: None)
    monkeypatch.setattr("main.get_status", lambda: ("head", "head"))
    monkeypatch.setattr("main.ensure_ongoing_series_table", lambda: False)
    monkeypatch.setattr("main.ensure_tags_tables", lambda: False)
    monkeypatch.setattr("main.start_file_monitoring", lambda cfg: None)
    monkeypatch.setattr("main.setup_logging", lambda: None)
    monkeypatch.setattr("main._ensure_config", lambda: _make_config(tmp_path / "lib"))
    monkeypatch.setattr("main.typer.echo", lambda *a, **k: None)

    from main import serve

    serve(host=None, port=None, no_watch=True)
    assert order == ["wait", "scan", "http"]



