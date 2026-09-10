"""Tests for series continuation and cross-issue reader navigation."""

from __future__ import annotations

import importlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, create_engine

from reader import series
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


def _series_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE comics (
            id INTEGER PRIMARY KEY,
            uuid TEXT NOT NULL,
            filename TEXT NOT NULL,
            page_count INTEGER NOT NULL,
            folder_id INTEGER
        );
        CREATE TABLE metadata (
            comic_id INTEGER PRIMARY KEY,
            title TEXT,
            issue_number INTEGER,
            current_page INTEGER,
            last_read_at TEXT,
            is_completed INTEGER DEFAULT 0
        );
        """
    )
    return conn


def _add_comic(
    conn: sqlite3.Connection,
    comic_id: int,
    filename: str,
    *,
    current_page: int | None = None,
    last_read_at: str | None = None,
    completed: bool = False,
) -> None:
    conn.execute(
        "INSERT INTO comics (id, uuid, filename, page_count, folder_id) VALUES (?, ?, ?, 20, 7)",
        (comic_id, f"comic-{comic_id}", filename),
    )
    conn.execute(
        """INSERT INTO metadata
           (comic_id, issue_number, current_page, last_read_at, is_completed)
           VALUES (?, ?, ?, ?, ?)""",
        (comic_id, comic_id, current_page, last_read_at, int(completed)),
    )
    conn.commit()


def test_continue_series_prefers_most_recent_in_progress_comic():
    conn = _series_connection()
    _add_comic(conn, 1, "Series 001.cbz")
    _add_comic(conn, 2, "Series 002.cbz", current_page=4, last_read_at="2026-01-01T10:00:00")
    _add_comic(conn, 3, "Series 003.cbz", current_page=2, last_read_at="2026-01-02T10:00:00")

    state = series.get_continue_series(conn, 7)

    assert state["status"] == "ready"
    assert state["resume"] is True
    assert state["target"]["uuid"] == "comic-3"


def test_continue_series_uses_first_unread_and_reports_all_read():
    conn = _series_connection()
    _add_comic(conn, 1, "Series 001.cbz", completed=True)
    _add_comic(conn, 10, "Series 010.cbz")
    _add_comic(conn, 2, "Series 002.cbz")

    state = series.get_continue_series(conn, 7)

    assert state["resume"] is False
    assert state["target"]["uuid"] == "comic-2"

    conn.execute("UPDATE metadata SET is_completed = 1")
    conn.commit()
    assert series.get_continue_series(conn, 7)["status"] == "all_read"


def test_incomplete_comic_left_on_last_page_restarts_from_beginning():
    conn = _series_connection()
    _add_comic(
        conn,
        1,
        "Series 001.cbz",
        current_page=20,
        last_read_at="2026-01-02T10:00:00",
    )

    state = series.get_continue_series(conn, 7)

    assert state["status"] == "ready"
    assert state["resume"] is False
    assert state["target"]["uuid"] == "comic-1"


def test_series_navigation_is_natural_and_surfaces_issue_gaps():
    conn = _series_connection()
    _add_comic(conn, 1, "Series 001 (2026).cbz")
    _add_comic(conn, 10, "Series 010 (2026).cbz")
    _add_comic(conn, 2, "Series 002 (2026).cbz")

    navigation = series.get_series_navigation(conn, "comic-2")

    assert navigation is not None
    assert navigation["position"] == 2
    assert navigation["previous"]["uuid"] == "comic-1"
    assert navigation["next"]["uuid"] == "comic-10"
    assert navigation["missing_issues_to_next"] == list(range(3, 10))


def test_empty_and_single_issue_series_have_clear_boundaries():
    conn = _series_connection()
    assert series.get_continue_series(conn, 7)["status"] == "empty"

    _add_comic(conn, 1, "One Shot.cbz")
    navigation = series.get_series_navigation(conn, "comic-1")

    assert navigation is not None
    assert navigation["position"] == 1
    assert navigation["total"] == 1
    assert navigation["previous"] is None
    assert navigation["next"] is None


@pytest.fixture
def continue_series_app(tmp_path, monkeypatch):
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
        f"sqlite:///{db_file}", connect_args={"check_same_thread": False}
    )
    monkeypatch.setattr("server.database.DB_PATH", db_file, raising=True)
    monkeypatch.setattr("server.database.engine", engine, raising=True)
    init_db()
    with sqlite3.connect(db_file) as conn:
        conn.execute(
            "CREATE TABLE ongoing_series (folder_id INTEGER PRIMARY KEY, marked_at DATETIME NOT NULL)"
        )

    common_module = importlib.import_module("reader.routes._common")
    auth_module = importlib.import_module("reader.routes.auth")
    middleware_module = importlib.import_module("server.opds.middleware")
    opds_routes_module = importlib.import_module("server.opds.routes")
    browse_module = importlib.import_module("reader.routes.browse")
    monkeypatch.setattr(common_module, "get_config", lambda: config)
    monkeypatch.setattr(auth_module, "get_config", lambda: config)
    monkeypatch.setattr(middleware_module, "get_config", lambda: config)
    monkeypatch.setattr(opds_routes_module, "get_config", lambda: config)

    with Session(engine) as session:
        folder = Folder(name="The Series", path="The Series")
        session.add(folder)
        session.commit()
        session.refresh(folder)
        folder_id = folder.id
        for number in (1, 2, 3):
            comic = Comic(
                uuid=f"issue-{number}",
                filename=f"The Series {number:03d} (2026).cbz",
                path=f"The Series/The Series {number:03d} (2026).cbz",
                format="cbz",
                file_size=100,
                page_count=12,
                file_modified_at=datetime.now(timezone.utc),
                folder_id=folder_id,
            )
            session.add(comic)
            session.commit()
            session.refresh(comic)
            session.add(
                ComicMetadata(
                    comic_id=comic.id,
                    issue_number=number,
                    current_page=8 if number == 2 else None,
                    last_read_at=(
                        datetime(2026, 1, 2, tzinfo=timezone.utc)
                        if number == 2
                        else None
                    ),
                    is_completed=number == 3,
                )
            )
            session.commit()

    monkeypatch.setattr(
        browse_module.services,
        "get_comic_by_uuid",
        lambda comic_uuid: (
            {"filename": f"{comic_uuid}.cbz", "page_count": 12}
            if comic_uuid != "missing"
            else None
        ),
    )
    return folder_id, TestClient(app, base_url="http://testserver")


def test_folder_and_navigation_api_expose_series_actions(continue_series_app):
    folder_id, client = continue_series_app

    folder_response = client.get(f"/reader/folder/{folder_id}")
    navigation_response = client.get("/reader/api/comic/issue-2/navigation")

    assert folder_response.status_code == 200
    assert "Continue series" in folder_response.text
    assert f"/reader/comic/issue-2?series={folder_id}" in folder_response.text
    assert navigation_response.status_code == 200
    navigation = navigation_response.json()
    assert navigation["previous"]["uuid"] == "issue-1"
    assert navigation["next"]["uuid"] == "issue-3"
    assert navigation["next"]["reader_url"].endswith(
        f"/reader/comic/issue-3?series={folder_id}&start=1"
    )


def test_reader_renders_issue_navigation_and_preserves_completed_state(continue_series_app):
    folder_id, client = continue_series_app

    response = client.get(f"/reader/comic/issue-3?series={folder_id}&start=1")

    assert response.status_code == 200
    assert 'data-initial-page="1"' in response.text
    assert 'data-was-completed="true"' in response.text
    assert "Issue 3 of 3" in response.text
    assert "Next issue" not in response.text
    assert 'class="reader-series-navigation' not in response.text
    assert "End of series" in response.text
    assert 'id="reader-series-end"' in response.text
    assert 'id="reader-progress-error"' in response.text

    script = Path(importlib.import_module("reader").__path__[0]) / "static/js/reader.js"
    script_text = script.read_text()
    assert "persistProgress(lastVisiblePage, { showError: true })" in script_text
    assert "if (saved) window.location.assign(link.href)" in script_text


def test_reader_end_panel_offers_the_next_issue(continue_series_app):
    folder_id, client = continue_series_app

    response = client.get(f"/reader/comic/issue-2?series={folder_id}")

    assert response.status_code == 200
    assert "Up next" in response.text
    assert "Read next issue" in response.text
    assert f"/reader/comic/issue-3?series={folder_id}&amp;start=1" in response.text
    assert "Issue 2 of 3" in response.text
    assert "Next issue" not in response.text
    assert 'class="reader-series-navigation' not in response.text


def test_missing_comic_in_series_context_has_a_return_path(continue_series_app):
    folder_id, client = continue_series_app

    response = client.get(f"/reader/comic/missing?series={folder_id}")

    assert response.status_code == 404
    assert "This comic is no longer available" in response.text
    assert f'href="/reader/folder/{folder_id}"' in response.text
