"""Tests for OPDS endpoints."""

import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, create_engine

from server.config import IssuedConfig, LibraryConfig, MonitoringConfig, ReaderAuthConfig, ScannerConfig, ServerConfig, ThumbnailConfig
from server.database import init_db
from server.opds import app
from server.repository import Repository
from server.models import Comic, Folder


@pytest.fixture
def test_config(tmp_path):
    """Create a test configuration."""
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
def test_db(tmp_path, monkeypatch):
    """Create a test database."""
    db_file = tmp_path / "test.db"
    monkeypatch.setattr("server.database.DB_PATH", db_file, raising=True)
    
    engine = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    monkeypatch.setattr("server.database.engine", engine, raising=True)
    
    init_db()
    return engine


@pytest.fixture
def client(test_config, test_db, monkeypatch):
    """Create a test client."""
    # Mock get_config to return our test config
    monkeypatch.setattr("server.opds.get_config", lambda: test_config)
    
    return TestClient(app)


def test_opds_root_returns_valid_xml(client):
    """Test that OPDS root returns valid XML."""
    response = client.get("/opds/")
    assert response.status_code == 200
    assert "application/atom+xml" in response.headers["content-type"]
    
    # Parse XML to ensure it's valid
    root = ET.fromstring(response.content)
    assert root.tag.endswith("feed")


def test_opds_root_has_required_elements(client):
    """Test that OPDS root has required OPDS elements."""
    response = client.get("/opds/")
    root = ET.fromstring(response.content)
    
    # Check for required elements (namespace-aware)
    ns = {'atom': 'http://www.w3.org/2005/Atom'}
    
    # Should have id, title, updated
    assert root.find('atom:id', ns) is not None
    assert root.find('atom:title', ns) is not None
    assert root.find('atom:updated', ns) is not None


def test_opds_search_returns_results(client, test_db, test_config):
    """Test that OPDS search returns results for matching comics."""
    # Add a test comic to the database
    with Session(test_db) as session:
        repo = Repository(session, test_config.library_path)
        folder = repo.get_or_create_folder(test_config.library_path)
        
        comic = Comic(
            filename="Batman #1.cbz",
            path="Batman #1.cbz",
            format="cbz",
            file_size=1000000,
            page_count=24,
            file_modified_at=datetime.now(),
            folder_id=folder.id,
        )
        session.add(comic)
        session.commit()
    
    # Search for the comic
    response = client.get("/opds/search?q=Batman")
    assert response.status_code == 200
    
    # Parse and check results
    root = ET.fromstring(response.content)
    ns = {'atom': 'http://www.w3.org/2005/Atom'}
    entries = root.findall('atom:entry', ns)
    
    assert len(entries) > 0


def test_opds_folder_endpoint_returns_404_for_missing(client):
    """Test that folder endpoint returns 404 for non-existent folder."""
    response = client.get("/opds/folder/999")
    assert response.status_code == 404


def test_opds_recent_endpoint_returns_xml(client):
    """Test that recent endpoint returns valid XML."""
    response = client.get("/opds/recent?limit=10")
    assert response.status_code == 200
    assert "application/atom+xml" in response.headers["content-type"]
    
    root = ET.fromstring(response.content)
    assert root.tag.endswith("feed")

