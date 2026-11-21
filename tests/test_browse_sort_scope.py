"""Sorting is opt-out: views such as Recent must stay chronological."""

import importlib
import sqlite3
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, create_engine

from server.config import (
    IssuedConfig,
    LibraryConfig,
    MonitoringConfig,
    ReaderAuthConfig,
    ScannerConfig,
    ServerConfig,
    ThumbnailConfig,
)
from server.database import init_db
from server.models import Comic, ComicMetadata, Folder
from server.opds import app


def _test_config(tmp_path):
    library_path = tmp_path / "comics"
    library_path.mkdir()
    return IssuedConfig(
        library=LibraryConfig(path=library_path, name="Test Library"),
        server=ServerConfig(),
        thumbnails=ThumbnailConfig(),
        scanner=ScannerConfig(),
        monitoring=MonitoringConfig(enabled=False),
        reader_auth=ReaderAuthConfig(),
    )


@pytest.fixture
def client(tmp_path, monkeypatch):
    config = _test_config(tmp_path)
    common_module = importlib.import_module("reader.routes._common")

    db_file = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    monkeypatch.setattr("server.database.DB_PATH", db_file, raising=True)
    monkeypatch.setattr("server.database.engine", engine, raising=True)
    init_db()
    with sqlite3.connect(db_file) as conn:
        conn.execute(
            "CREATE TABLE ongoing_series (folder_id INTEGER PRIMARY KEY, marked_at DATETIME NOT NULL)"
        )

    monkeypatch.setattr("server.opds.get_config", lambda: config)
    monkeypatch.setattr(common_module, "get_config", lambda: config)

    with Session(engine) as session:
        folder = Folder(name="Shelf", path="Shelf")
        session.add(folder)
        session.commit()
        session.refresh(folder)
        for number, title in ((1, "Zeta"), (2, "Alpha")):
            comic = Comic(
                uuid=f"comic-{number}",
                filename=f"{title}.cbz",
                path=f"Shelf/{title}.cbz",
                format="cbz",
                file_size=100,
                page_count=12,
                file_modified_at=datetime.now(timezone.utc),
                last_scanned_at=datetime(2026, 1, number, tzinfo=timezone.utc),
                folder_id=folder.id,
            )
            session.add(comic)
            session.commit()
            session.refresh(comic)
            session.add(
                ComicMetadata(
                    comic_id=comic.id,
                )
            )
            session.commit()

    return TestClient(app)


def test_recent_page_is_chronological_and_hides_sort_controls(client):
    response = client.get("/reader/recent")

    assert response.status_code == 200
    assert 'data-sortable="false"' in response.text
    assert "data-sort-order=" not in response.text
    assert "Sort by" not in response.text
    # Server order (newest first) is left untouched: Alpha is newer than Zeta.
    assert response.text.index("Alpha") < response.text.index("Zeta")


def test_browse_page_offers_sort_controls(client):
    response = client.get("/reader/")

    assert response.status_code == 200
    assert 'data-sortable="true"' in response.text
    assert 'data-sort-order="newest"' in response.text
    assert "Sort by" in response.text
