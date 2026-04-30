"""Tests for manual scan action in reader menu."""

import importlib

from fastapi.testclient import TestClient
from sqlmodel import create_engine

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


def test_reader_scan_endpoint_returns_stats(tmp_path, monkeypatch):
    config = _test_config(tmp_path)
    reader_router_module = importlib.import_module("reader.router")

    db_file = tmp_path / "test.db"
    monkeypatch.setattr("server.database.DB_PATH", db_file, raising=True)
    monkeypatch.setattr(
        "server.database.engine",
        create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False}),
        raising=True,
    )
    init_db()

    monkeypatch.setattr("server.opds.get_config", lambda: config)
    monkeypatch.setattr(reader_router_module, "get_config", lambda: config)
    monkeypatch.setattr(
        reader_router_module,
        "scan_library",
        lambda cfg: {"added": 1, "updated": 2, "deleted": 0, "skipped": 3},
    )

    client = TestClient(app)
    response = client.post("/reader/api/library/scan")

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "stats": {"added": 1, "updated": 2, "deleted": 0, "skipped": 3},
    }


def test_reader_root_renders_scan_button(tmp_path, monkeypatch):
    config = _test_config(tmp_path)
    reader_router_module = importlib.import_module("reader.router")

    db_file = tmp_path / "test.db"
    monkeypatch.setattr("server.database.DB_PATH", db_file, raising=True)
    monkeypatch.setattr(
        "server.database.engine",
        create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False}),
        raising=True,
    )
    init_db()

    monkeypatch.setattr("server.opds.get_config", lambda: config)
    monkeypatch.setattr(reader_router_module, "get_config", lambda: config)

    client = TestClient(app)
    response = client.get("/reader/")

    assert response.status_code == 200
    assert 'id="scan-library-btn"' in response.text


def test_reader_recent_renders_scan_button(tmp_path, monkeypatch):
    config = _test_config(tmp_path)
    reader_router_module = importlib.import_module("reader.router")

    db_file = tmp_path / "test.db"
    monkeypatch.setattr("server.database.DB_PATH", db_file, raising=True)
    monkeypatch.setattr(
        "server.database.engine",
        create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False}),
        raising=True,
    )
    init_db()

    monkeypatch.setattr("server.opds.get_config", lambda: config)
    monkeypatch.setattr(reader_router_module, "get_config", lambda: config)

    client = TestClient(app)
    response = client.get("/reader/recent")

    assert response.status_code == 200
    assert 'id="scan-library-btn"' in response.text
