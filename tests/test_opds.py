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
from server.opds.feeds import _comic_media_type


@pytest.fixture
def test_config(tmp_path, monkeypatch):
    """Create a test configuration."""
    monkeypatch.setattr("server.config.DATA_DIR", tmp_path, raising=True)
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
    monkeypatch.setattr("server.opds.routes.get_config", lambda: test_config)
    
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


def test_opds_folder_entries_include_nested_comic_thumbnail(
    client,
    test_config,
    test_db,
):
    """Navigation folders use the newest successfully generated subtree cover."""
    with Session(test_db) as session:
        library = Folder(name="Comics", path=".")
        session.add(library)
        session.commit()
        session.refresh(library)

        series = Folder(name="Example Series", path="Example Series", parent_id=library.id)
        session.add(series)
        session.commit()
        session.refresh(series)
        library_id = library.id

        valid_comic = Comic(
            uuid="folder-preview-comic",
            filename="Issue 1.cbz",
            path="Example Series/Issue 1.cbz",
            format="cbz",
            file_size=100,
            page_count=12,
            file_modified_at=datetime(2026, 1, 1),
            last_scanned_at=datetime(2026, 1, 1),
            thumbnail_generated=True,
            folder_id=series.id,
        )
        session.add(valid_comic)
        session.add(
            Comic(
                uuid="missing-newer-thumbnail",
                filename="Issue 2.cbz",
                path="Example Series/Issue 2.cbz",
                format="cbz",
                file_size=100,
                page_count=12,
                file_modified_at=datetime(2026, 2, 1),
                last_scanned_at=datetime(2026, 2, 1),
                thumbnail_generated=False,
                folder_id=series.id,
            )
        )
        session.commit()

    test_config.thumbnails_dir.mkdir()
    (test_config.thumbnails_dir / "folder-preview-comic.webp").write_bytes(b"webp")

    ns = {'atom': 'http://www.w3.org/2005/Atom'}
    expected_href = "http://testserver/opds/comic/folder-preview-comic/thumbnail"

    root_response = client.get("/opds/")
    root_entry = ET.fromstring(root_response.content).find('atom:entry', ns)
    root_thumbnail = root_entry.find(
        "atom:link[@rel='http://opds-spec.org/image/thumbnail']",
        ns,
    )
    assert root_thumbnail is not None
    assert root_thumbnail.attrib == {
        "rel": "http://opds-spec.org/image/thumbnail",
        "href": expected_href,
        "type": "image/webp",
    }
    assert client.get(root_thumbnail.attrib["href"]).status_code == 200

    recent_entry = next(
        entry
        for entry in ET.fromstring(root_response.content).findall('atom:entry', ns)
        if entry.find('atom:id', ns).text == "urn:recent"
    )
    recent_thumbnail = recent_entry.find(
        "atom:link[@rel='http://opds-spec.org/image/thumbnail']",
        ns,
    )
    assert recent_thumbnail is not None
    assert recent_thumbnail.attrib["href"] == expected_href

    folder_response = client.get(f"/opds/folder/{library_id}")
    folder_entry = ET.fromstring(folder_response.content).find('atom:entry', ns)
    folder_thumbnail = folder_entry.find(
        "atom:link[@rel='http://opds-spec.org/image/thumbnail']",
        ns,
    )
    assert folder_thumbnail is not None
    assert folder_thumbnail.attrib["href"] == expected_href


def test_recent_preview_matches_first_entry_when_scan_times_are_tied(
    client,
    test_config,
    test_db,
):
    """Recent artwork and feed use the same deterministic tie-breaker."""
    tied_scan_time = datetime(2026, 3, 1)
    with Session(test_db) as session:
        library = Folder(name="Comics", path=".")
        session.add(library)
        session.commit()
        session.refresh(library)

        for index in (1, 2):
            session.add(
                Comic(
                    uuid=f"recent-{index}",
                    filename=f"Issue {index}.cbz",
                    path=f"Issue {index}.cbz",
                    format="cbz",
                    file_size=100,
                    page_count=12,
                    file_modified_at=tied_scan_time,
                    last_scanned_at=tied_scan_time,
                    thumbnail_generated=True,
                    folder_id=library.id,
                )
            )
        session.commit()

    test_config.thumbnails_dir.mkdir()
    for index in (1, 2):
        (test_config.thumbnails_dir / f"recent-{index}.webp").write_bytes(b"webp")

    ns = {'atom': 'http://www.w3.org/2005/Atom'}
    root = ET.fromstring(client.get("/opds/").content)
    recent_navigation = next(
        entry
        for entry in root.findall('atom:entry', ns)
        if entry.find('atom:id', ns).text == "urn:recent"
    )
    preview_href = recent_navigation.find(
        "atom:link[@rel='http://opds-spec.org/image/thumbnail']",
        ns,
    ).attrib["href"]

    recent_feed = ET.fromstring(client.get("/opds/recent").content)
    first_recent_id = recent_feed.find('atom:entry/atom:id', ns).text

    assert preview_href.endswith("/recent-2/thumbnail")
    assert first_recent_id == "urn:comic:recent-2"


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


def _atom_search_link(xml: bytes):
    ns = {'atom': 'http://www.w3.org/2005/Atom'}
    return ET.fromstring(xml).find("atom:link[@rel='search']", ns)


def test_opds_feeds_advertise_opensearch(client):
    """Root and other catalog feeds link to the OpenSearch description."""
    expected = {
        "rel": "search",
        "href": "http://testserver/opds/search.xml",
        "type": "application/opensearchdescription+xml",
    }

    root_link = _atom_search_link(client.get("/opds/").content)
    assert root_link is not None
    assert root_link.attrib == expected

    recent_link = _atom_search_link(client.get("/opds/recent").content)
    assert recent_link is not None
    assert recent_link.attrib == expected


def test_opensearch_description_document(client):
    """OpenSearch OSD uses an OPDS acquisition template with {searchTerms}."""
    response = client.get("/opds/search.xml")
    assert response.status_code == 200
    assert "application/opensearchdescription+xml" in response.headers["content-type"]

    ns = {'os': 'http://a9.com/-/spec/opensearch/1.1/'}
    root = ET.fromstring(response.content)
    assert root.tag == "{http://a9.com/-/spec/opensearch/1.1/}OpenSearchDescription"
    assert root.find('os:ShortName', ns).text == "Test Library"
    assert root.find('os:Description', ns).text == "Search Test Library"

    url = root.find('os:Url', ns)
    assert url is not None
    assert url.attrib["type"] == "application/atom+xml;profile=opds-catalog;kind=acquisition"
    assert url.attrib["template"] == "http://testserver/opds/search?q={searchTerms}"


def test_opds_search_autodiscovery_flow(client, test_db, test_config):
    """Clients follow root → OSD → search template substitution."""
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

    search_link = _atom_search_link(client.get("/opds/").content)
    osd = ET.fromstring(client.get(search_link.attrib["href"]).content)
    template = osd.find(
        '{http://a9.com/-/spec/opensearch/1.1/}Url'
    ).attrib["template"]
    results = client.get(template.replace("{searchTerms}", "Batman"))

    assert results.status_code == 200
    ns = {'atom': 'http://www.w3.org/2005/Atom'}
    entries = ET.fromstring(results.content).findall('atom:entry', ns)
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


def test_cb7_media_type():
    assert _comic_media_type("cb7") == "application/x-7z-compressed"


def test_misnamed_cb7_download_uses_real_format(client, test_db, test_config):
    comic_path = test_config.library_path / "misnamed.cbz"
    payload = b"7z\xbc\xaf\x27\x1carchive-data"
    comic_path.write_bytes(payload)

    with Session(test_db) as session:
        repo = Repository(session, test_config.library_path)
        folder = repo.get_or_create_folder(test_config.library_path)
        comic = Comic(
            filename=comic_path.name,
            path=comic_path.name,
            format="cb7",
            file_size=len(payload),
            page_count=1,
            file_modified_at=datetime.now(),
            folder_id=folder.id,
        )
        session.add(comic)
        session.commit()
        session.refresh(comic)
        comic_uuid = comic.uuid

    response = client.get(f"/opds/comic/{comic_uuid}/file")

    assert response.status_code == 200
    assert response.content == payload
    assert response.headers["content-type"] == "application/x-7z-compressed"
    assert 'filename="misnamed.cb7"' in response.headers["content-disposition"]
