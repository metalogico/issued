"""CB7 support and content-based archive detection tests."""

from __future__ import annotations

import io
import sqlite3
from pathlib import Path

import py7zr
import pytest
from PIL import Image
from sqlmodel import create_engine

from server import scanner
from server.archive import (
    ComicFormat,
    RAR4_MAGIC_HEADER,
    RAR5_MAGIC_HEADER,
    SEVEN_ZIP_MAGIC_HEADER,
    SevenZipArchiveWrapper,
    detect_archive_format,
    detect_format_from_header,
    get_archive,
)
from server.config import (
    IssuedConfig,
    LibraryConfig,
    MonitoringConfig,
    ReaderAuthConfig,
    ScannerConfig,
    ServerConfig,
    ThumbnailConfig,
)


def _png_bytes(color: str = "red") -> bytes:
    image = Image.new("RGB", (10, 10), color=color)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _create_cb7(path: Path, work_dir: Path) -> None:
    source = work_dir / f"source-{path.stem}"
    pages = source / "pages"
    pages.mkdir(parents=True)
    (pages / "page10.png").write_bytes(_png_bytes("blue"))
    (pages / "page2.png").write_bytes(_png_bytes("red"))
    (source / "ComicInfo.xml").write_text(
        "<ComicInfo><Title>CB7 Test</Title><PageCount>2</PageCount></ComicInfo>",
        encoding="utf-8",
    )
    with py7zr.SevenZipFile(path, mode="w") as archive:
        archive.write(pages / "page10.png", "pages/page10.png")
        archive.write(pages / "page2.png", "pages/page2.png")
        archive.write(source / "ComicInfo.xml", "ComicInfo.xml")


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (b"PK\x03\x04extra", ComicFormat.CBZ),
        (b"PK\x05\x06extra", ComicFormat.CBZ),
        (b"PK\x07\x08extra", ComicFormat.CBZ),
        (RAR4_MAGIC_HEADER + b"extra", ComicFormat.CBR),
        (RAR5_MAGIC_HEADER + b"extra", ComicFormat.CBR),
        (SEVEN_ZIP_MAGIC_HEADER + b"extra", ComicFormat.CB7),
        (b"%PDF-1.7", ComicFormat.PDF),
    ],
)
def test_detect_format_from_magic_header(header, expected):
    assert detect_format_from_header(header) == expected


@pytest.mark.parametrize("header", [b"", b"P", b"PK", b"Rar!", b"7z", b"unknown"])
def test_detect_format_rejects_truncated_or_unknown_headers(header):
    assert detect_format_from_header(header) is None


def test_detection_ignores_misleading_extension(tmp_path):
    comic = tmp_path / "misnamed.cbz"
    comic.write_bytes(SEVEN_ZIP_MAGIC_HEADER + b"not-a-complete-archive")
    assert detect_archive_format(comic) == ComicFormat.CB7


def test_detection_reports_unknown_container(tmp_path):
    comic = tmp_path / "broken.cb7"
    comic.write_bytes(b"not an archive")
    with pytest.raises(ValueError, match="unrecognized magic header"):
        detect_archive_format(comic)


def test_cb7_wrapper_lists_and_reads_members_repeatedly(tmp_path):
    comic = tmp_path / "comic.cb7"
    _create_cb7(comic, tmp_path)

    assert detect_archive_format(comic) == ComicFormat.CB7
    with get_archive(comic) as archive:
        assert isinstance(archive, SevenZipArchiveWrapper)
        assert set(archive.list_images()) == {
            "pages/page2.png",
            "pages/page10.png",
        }
        assert "ComicInfo.xml" in archive.list_names()
        first = archive.read("pages/page2.png")
        second = archive.read("pages/page2.png")
        assert first == second
        assert first.startswith(b"\x89PNG")
        assert b"CB7 Test" in archive.read("ComicInfo.xml")


def test_corrupt_cb7_reports_clear_error(tmp_path):
    comic = tmp_path / "corrupt.cb7"
    comic.write_bytes(SEVEN_ZIP_MAGIC_HEADER + b"broken")

    with pytest.raises(ValueError, match="Cannot open CB7 archive"):
        get_archive(comic)


def test_password_protected_cb7_reports_clear_error(tmp_path):
    source = tmp_path / "secret.png"
    source.write_bytes(_png_bytes())
    comic = tmp_path / "encrypted.cb7"
    with py7zr.SevenZipFile(comic, mode="w", password="secret") as archive:
        archive.write(source, "secret.png")

    with pytest.raises(ValueError, match="Password-protected CB7 archive"):
        get_archive(comic)


def test_scanner_rejects_cb7_without_images(tmp_path):
    source = tmp_path / "notes.txt"
    source.write_text("no comic pages", encoding="utf-8")
    comic = tmp_path / "empty.cb7"
    with py7zr.SevenZipFile(comic, mode="w") as archive:
        archive.write(source, "notes.txt")

    with pytest.raises(ValueError, match="No supported images found"):
        scanner.validate_and_count_pages(comic)


def _make_config(library: Path) -> IssuedConfig:
    return IssuedConfig(
        library=LibraryConfig(path=library, name="Test Library"),
        server=ServerConfig(),
        thumbnails=ThumbnailConfig(),
        scanner=ScannerConfig(),
        monitoring=MonitoringConfig(enabled=False),
        reader_auth=ReaderAuthConfig(),
    )


def _configure_test_database(tmp_path, monkeypatch) -> Path:
    db_file = tmp_path / "library.db"
    engine = create_engine(
        f"sqlite:///{db_file}", connect_args={"check_same_thread": False}
    )
    monkeypatch.setattr("server.database.DB_PATH", db_file, raising=True)
    monkeypatch.setattr("server.database.engine", engine, raising=True)
    monkeypatch.setattr("server.config.DATA_DIR", tmp_path, raising=True)
    return db_file


@pytest.mark.parametrize("extension", [".cb7", ".cbz"])
def test_scanner_imports_cb7_and_persists_real_format(tmp_path, monkeypatch, extension):
    library = tmp_path / "library"
    series = library / "Series"
    series.mkdir(parents=True)
    comic = series / f"issue01{extension}"
    _create_cb7(comic, tmp_path)
    db_file = _configure_test_database(tmp_path, monkeypatch)

    stats = scanner.scan_library(_make_config(library), force=True)

    assert stats["added"] == 1
    with sqlite3.connect(db_file) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT c.format, c.page_count, c.thumbnail_generated, m.title "
            "FROM comics c JOIN metadata m ON m.comic_id = c.id"
        ).fetchone()
        assert row["format"] == "cb7"
        assert row["page_count"] == 2
        assert row["thumbnail_generated"] == 1
        assert row["title"] == "CB7 Test"


def test_scanner_reclassifies_unchanged_legacy_record(tmp_path, monkeypatch):
    library = tmp_path / "library"
    library.mkdir()
    comic = library / "legacy.cbz"
    _create_cb7(comic, tmp_path)
    db_file = _configure_test_database(tmp_path, monkeypatch)
    config = _make_config(library)

    scanner.scan_library(config, force=True)
    with sqlite3.connect(db_file) as connection:
        connection.execute("UPDATE comics SET format = 'cbz'")
        connection.commit()

    stats = scanner.scan_library(config, force=False)

    assert stats["updated"] == 1
    with sqlite3.connect(db_file) as connection:
        actual = connection.execute("SELECT format FROM comics").fetchone()[0]
    assert actual == "cb7"


def test_cb7_extension_is_supported_but_plain_7z_is_not():
    assert scanner.is_comic_file(Path("comic.cb7"))
    assert scanner.is_comic_file(Path("COMIC.CB7"))
    assert not scanner.is_comic_file(Path("archive.7z"))
