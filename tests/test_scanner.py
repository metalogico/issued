import io
import sqlite3
import zipfile
from pathlib import Path

from PIL import Image

from server.config import IssuedConfig, LibraryConfig, MonitoringConfig, ReaderAuthConfig, ScannerConfig, ServerConfig, ThumbnailConfig
from server.database import DB_PATH, get_connection, init_db
from server import scanner


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


