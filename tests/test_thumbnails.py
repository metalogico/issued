from sqlmodel import Session, select

from server.database import get_engine
from server.models import Comic
from server.thumbnails import generate_thumbnails
from tests.test_scanner import _create_minimal_cbz, _make_config, _patch_db
from server import scanner


def test_generate_thumbnails_rebuilds_missing_webp(tmp_path, monkeypatch):
    lib = tmp_path / "lib"
    lib.mkdir()
    _create_minimal_cbz(lib / "issue01.cbz")
    _patch_db(tmp_path, monkeypatch)
    monkeypatch.setattr("server.config.DATA_DIR", tmp_path, raising=True)

    config = _make_config(lib)
    scanner.scan_library(config, force=True)

    with Session(get_engine()) as session:
        comic = session.exec(select(Comic)).one()
        comic_uuid = comic.uuid
        assert comic.thumbnail_generated is True

    thumb = tmp_path / "thumbnails" / f"{comic_uuid}.webp"
    assert thumb.exists()
    thumb.unlink()

    generate_thumbnails(config, regenerate=False)
    assert thumb.exists()
