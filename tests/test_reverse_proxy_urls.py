"""Regression tests for reader URLs generated behind a reverse proxy."""

from __future__ import annotations

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
from server.models import Comic, Folder
from server.opds import app


@pytest.fixture
def proxy_app(tmp_path, monkeypatch):
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
    engine = create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False},
    )
    monkeypatch.setattr("server.database.DB_PATH", db_file, raising=True)
    monkeypatch.setattr("server.database.engine", engine, raising=True)
    init_db()
    with sqlite3.connect(db_file) as conn:
        conn.execute(
            """
            CREATE TABLE ongoing_series (
                folder_id INTEGER NOT NULL PRIMARY KEY,
                marked_at DATETIME NOT NULL
            )
            """
        )

    common_module = importlib.import_module("reader.routes._common")
    auth_module = importlib.import_module("reader.routes.auth")
    middleware_module = importlib.import_module("server.opds.middleware")
    opds_routes_module = importlib.import_module("server.opds.routes")
    monkeypatch.setattr(common_module, "get_config", lambda: config)
    monkeypatch.setattr(auth_module, "get_config", lambda: config)
    monkeypatch.setattr(middleware_module, "get_config", lambda: config)
    monkeypatch.setattr(opds_routes_module, "get_config", lambda: config)

    client = TestClient(app, base_url="http://issued.internal:8181")
    return config, engine, client


def test_reader_html_uses_origin_relative_asset_and_thumbnail_urls(proxy_app):
    _, engine, client = proxy_app
    with Session(engine) as session:
        folder = Folder(name="Series", path="Series")
        session.add(folder)
        session.commit()
        session.refresh(folder)
        session.add(
            Comic(
                uuid="proxy-comic",
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

    response = client.get("/reader/")

    assert response.status_code == 200
    assert 'href="/reader/static/css/style.css"' in response.text
    assert 'src="/reader/static/js/browser.js"' in response.text
    assert 'href="/reader/comic/proxy-comic"' in response.text
    assert 'src="/opds/comic/proxy-comic/thumbnail"' in response.text
    assert "issued.internal:8181" not in response.text


def test_reader_page_uses_origin_relative_page_image_url(proxy_app, monkeypatch):
    _, _, client = proxy_app
    browse_module = importlib.import_module("reader.routes.browse")
    monkeypatch.setattr(
        browse_module.services,
        "get_comic_by_uuid",
        lambda comic_uuid: {
            "filename": "Issue 1.cbz",
            "page_count": 12,
        },
    )
    monkeypatch.setattr(browse_module.repo, "get_initial_page", lambda *args: 1)
    monkeypatch.setattr(browse_module.repo, "get_folder_id_for_comic", lambda *args: None)
    monkeypatch.setattr(
        browse_module.repo,
        "get_metadata",
        lambda *args: None,
    )

    response = client.get("/reader/comic/proxy-comic")

    assert response.status_code == 200
    assert 'src="/reader/api/comic/proxy-comic/page/1"' in response.text
    assert 'src="/reader/static/js/reader.js"' in response.text
    assert "issued.internal:8181" not in response.text


def test_reader_auth_pages_and_redirects_use_origin_relative_urls(proxy_app):
    config, _, client = proxy_app

    redirect = client.get("/reader/login", follow_redirects=False)
    logout = client.post("/reader/logout", follow_redirects=False)

    assert redirect.headers["location"] == "/reader/"
    assert logout.headers["location"] == "/reader/login"

    config.reader_auth = ReaderAuthConfig(user="reader", password="secret")
    login = client.get("/reader/login")

    assert login.status_code == 200
    assert 'href="/reader/static/css/style.css"' in login.text
    assert 'action="/reader/login"' in login.text
    assert "issued.internal:8181" not in login.text


def test_opds_feed_keeps_absolute_public_urls(proxy_app):
    _, _, _ = proxy_app
    client = TestClient(app, base_url="https://issued.example.com")

    response = client.get("/opds/")

    assert response.status_code == 200
    assert 'href="https://issued.example.com/opds/"' in response.text
