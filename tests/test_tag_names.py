"""Tag names with URL-significant characters must not break the tag pages."""

from __future__ import annotations

import importlib
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from urllib.parse import quote

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
from server.models import Comic, Folder
from server.opds import app

TAG_NAMES = ["Action/Adventure", "Sci#Fi", "What?", "100%", "Plain"]


@pytest.fixture
def tagged_app(tmp_path, monkeypatch):
    library_path = tmp_path / "comics"
    library_path.mkdir()
    config = IssuedConfig(
        library=LibraryConfig(path=library_path, name="Test Library"),
        server=ServerConfig(),
        thumbnails=ThumbnailConfig(),
        scanner=ScannerConfig(),
        monitoring=MonitoringConfig(enabled=False),
        reader_auth=ReaderAuthConfig(),
    )

    db_file = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    monkeypatch.setattr("server.database.DB_PATH", db_file, raising=True)
    monkeypatch.setattr("server.database.engine", engine, raising=True)
    init_db()

    for module in (
        "reader.routes._common",
        "reader.routes.auth",
        "server.opds.middleware",
        "server.opds.routes",
    ):
        monkeypatch.setattr(importlib.import_module(module), "get_config", lambda: config)

    with Session(engine) as session:
        folder = Folder(name="Series", path="Series")
        session.add(folder)
        session.commit()
        session.refresh(folder)
        session.add(
            Comic(
                uuid="tagged-comic",
                filename="Issue 1.cbz",
                path="Series/Issue 1.cbz",
                format="cbz",
                file_size=100,
                page_count=12,
                file_modified_at=datetime.now(timezone.utc),
                folder_id=folder.id,
            )
        )
        session.commit()

    with closing(sqlite3.connect(db_file)) as conn, conn:
        comic_id = conn.execute("SELECT id FROM comics").fetchone()[0]
        for name in TAG_NAMES:
            cur = conn.execute("INSERT INTO tags (name) VALUES (?)", (name,))
            conn.execute(
                "INSERT INTO comic_tags (comic_id, tag_id) VALUES (?, ?)", (comic_id, cur.lastrowid)
            )

    yield db_file, TestClient(app)
    engine.dispose()


def test_tag_index_links_open_their_own_tag(tagged_app):
    _, client = tagged_app

    response = client.get("/reader/tags")
    assert response.status_code == 200

    hrefs = re.findall(r'href="(/reader/tags/[^"]+)"', response.text)
    assert len(hrefs) == len(TAG_NAMES)
    for name in TAG_NAMES:
        href = f"/reader/tags/{quote(name, safe='')}"
        assert href in hrefs
        page = client.get(href)
        assert page.status_code == 200
        assert "Issue 1.cbz" in page.text


@pytest.mark.parametrize("name", TAG_NAMES)
def test_delete_tag_with_special_characters(tagged_app, name):
    db_file, client = tagged_app

    # same encoding as the page's fetch(): encodeURIComponent
    response = client.delete(f"/reader/api/tags/{quote(name, safe='')}")
    assert response.status_code == 200

    with closing(sqlite3.connect(db_file)) as conn:
        names = {row[0] for row in conn.execute("SELECT name FROM tags")}
    assert name not in names
    assert len(names) == len(TAG_NAMES) - 1
