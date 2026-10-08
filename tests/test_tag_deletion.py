"""Deleting a tagged comic must not break the scan (comic_tags FK)."""

import io
import sqlite3
import zipfile
from pathlib import Path

import pytest
from PIL import Image
from sqlmodel import create_engine

from server import scanner
from server.config import (
    IssuedConfig,
    LibraryConfig,
    MonitoringConfig,
    ReaderAuthConfig,
    ScannerConfig,
    ServerConfig,
    ThumbnailConfig,
)


def _create_minimal_cbz(path: Path) -> None:
    img = Image.new("RGB", (10, 10), color="red")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("page001.png", buf.getvalue())


def _make_config(lib: Path) -> IssuedConfig:
    return IssuedConfig(
        library=LibraryConfig(path=lib, name="Test Library"),
        server=ServerConfig(),
        thumbnails=ThumbnailConfig(),
        scanner=ScannerConfig(),
        monitoring=MonitoringConfig(),
        reader_auth=ReaderAuthConfig(),
    )


def _patch_db(tmp_path, monkeypatch) -> Path:
    db_file = tmp_path / "library.db"
    monkeypatch.setattr("server.database.DB_PATH", db_file, raising=True)
    monkeypatch.setattr(
        "server.database.engine",
        create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False}),
        raising=True,
    )
    return db_file


LEGACY_COMIC_TAGS = """
    CREATE TABLE comic_tags (
        comic_id INTEGER NOT NULL,
        tag_id INTEGER NOT NULL,
        PRIMARY KEY (comic_id, tag_id),
        FOREIGN KEY(comic_id) REFERENCES comics (id),
        FOREIGN KEY(tag_id) REFERENCES tags (id)
    )
"""


def _use_legacy_comic_tags(db_file: Path) -> None:
    """Recreate comic_tags as older create_all() builds did: no ON DELETE CASCADE."""
    conn = sqlite3.connect(db_file)
    try:
        conn.execute("DROP TABLE comic_tags")
        conn.execute(LEGACY_COMIC_TAGS)
        conn.commit()
    finally:
        conn.close()


def _tag_all_comics(db_file: Path, tag: str = "Fantasy") -> None:
    conn = sqlite3.connect(db_file)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("INSERT INTO tags (name) VALUES (?)", (tag,))
        tag_id = conn.execute("SELECT id FROM tags WHERE name = ?", (tag,)).fetchone()[0]
        conn.execute(
            "INSERT INTO comic_tags (comic_id, tag_id) SELECT id, ? FROM comics", (tag_id,)
        )
        conn.commit()
    finally:
        conn.close()


def _library(tmp_path: Path) -> tuple[Path, Path, Path]:
    lib = tmp_path / "lib"
    series = lib / "Series"
    series.mkdir(parents=True)
    keep, drop = series / "keep.cbz", series / "drop.cbz"
    _create_minimal_cbz(keep)
    _create_minimal_cbz(drop)
    return lib, keep, drop


@pytest.mark.parametrize("legacy_schema", [False, True])
def test_scan_deletes_tagged_comic(tmp_path, monkeypatch, legacy_schema):
    lib, _, drop = _library(tmp_path)
    db_file = _patch_db(tmp_path, monkeypatch)
    config = _make_config(lib)
    scanner.scan_library(config, force=True)
    if legacy_schema:
        _use_legacy_comic_tags(db_file)
    _tag_all_comics(db_file)

    drop.unlink()
    stats = scanner.scan_library(config)

    assert stats["deleted"] == 1
    conn = sqlite3.connect(db_file)
    try:
        assert {r[0] for r in conn.execute("SELECT filename FROM comics")} == {"keep.cbz"}
        # the surviving comic keeps its tag, the deleted one leaves no orphan row
        assert conn.execute("SELECT COUNT(*) FROM comic_tags").fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM comic_tags WHERE comic_id NOT IN (SELECT id FROM comics)"
        ).fetchone()[0] == 0
    finally:
        conn.close()


@pytest.mark.parametrize("legacy_schema", [False, True])
def test_delete_path_removes_tagged_folder(tmp_path, monkeypatch, legacy_schema):
    lib, _, _ = _library(tmp_path)
    db_file = _patch_db(tmp_path, monkeypatch)
    config = _make_config(lib)
    scanner.scan_library(config, force=True)
    if legacy_schema:
        _use_legacy_comic_tags(db_file)
    _tag_all_comics(db_file)

    # simulate the file monitor reporting the whole folder as removed
    scanner.delete_path(lib / "Series", config)

    conn = sqlite3.connect(db_file)
    try:
        assert conn.execute("SELECT COUNT(*) FROM comics").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM comic_tags").fetchone()[0] == 0
    finally:
        conn.close()


def _comic_tags_sql(db_file: Path) -> str:
    conn = sqlite3.connect(db_file)
    try:
        return conn.execute("SELECT sql FROM sqlite_master WHERE name = 'comic_tags'").fetchone()[0]
    finally:
        conn.close()


def test_repair_adds_cascade_and_keeps_tags(tmp_path, monkeypatch):
    lib, _, _ = _library(tmp_path)
    db_file = _patch_db(tmp_path, monkeypatch)
    monkeypatch.setattr("server.migrations.DB_PATH", db_file, raising=True)
    config = _make_config(lib)
    scanner.scan_library(config, force=True)
    _use_legacy_comic_tags(db_file)
    _tag_all_comics(db_file)
    conn = sqlite3.connect(db_file)
    try:
        # an orphan link, as a legacy DB may hold one: dropped by the repair
        conn.execute("INSERT INTO comic_tags (comic_id, tag_id) VALUES (9999, 1)")
        conn.commit()
    finally:
        conn.close()

    from server.migrations import ensure_comic_tags_cascade

    assert ensure_comic_tags_cascade() is True
    assert _comic_tags_sql(db_file).upper().count("ON DELETE CASCADE") == 2
    assert ensure_comic_tags_cascade() is False  # idempotent

    conn = sqlite3.connect(db_file)
    try:
        assert conn.execute("SELECT COUNT(*) FROM comic_tags").fetchone()[0] == 2
        # with the cascade in place, a raw delete no longer violates the FK
        conn.execute("PRAGMA foreign_keys=ON")
        drop_id = conn.execute("SELECT id FROM comics WHERE filename = 'drop.cbz'").fetchone()[0]
        conn.execute("DELETE FROM metadata WHERE comic_id = ?", (drop_id,))  # ORM-cascaded in the app
        conn.execute("DELETE FROM comics WHERE id = ?", (drop_id,))
        conn.commit()
        assert conn.execute("SELECT COUNT(*) FROM comic_tags").fetchone()[0] == 1
    finally:
        conn.close()


def test_repair_leaves_current_schema_alone(tmp_path, monkeypatch):
    lib, _, _ = _library(tmp_path)
    db_file = _patch_db(tmp_path, monkeypatch)
    monkeypatch.setattr("server.migrations.DB_PATH", db_file, raising=True)
    scanner.scan_library(_make_config(lib), force=True)
    before = _comic_tags_sql(db_file)

    from server.migrations import ensure_comic_tags_cascade

    assert ensure_comic_tags_cascade() is False
    assert _comic_tags_sql(db_file) == before
