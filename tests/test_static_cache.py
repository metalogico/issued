from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.opds import RevalidatedStaticFiles, app


def _client(tmp_path):
    (tmp_path / "reader.js").write_text("console.log('v1');", encoding="utf-8")
    static_app = FastAPI()
    static_app.mount("/static", RevalidatedStaticFiles(directory=str(tmp_path)), name="static")
    return TestClient(static_app)


def test_static_files_must_be_revalidated(tmp_path):
    response = _client(tmp_path).get("/static/reader.js")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["etag"]


def test_unchanged_static_file_is_answered_with_not_modified(tmp_path):
    client = _client(tmp_path)
    etag = client.get("/static/reader.js").headers["etag"]

    response = client.get("/static/reader.js", headers={"If-None-Match": etag})

    assert response.status_code == 304
    assert response.headers["cache-control"] == "no-cache"


def test_reader_static_mount_uses_revalidated_files():
    mount = next(route for route in app.routes if getattr(route, "name", None) == "reader_static")

    assert isinstance(mount.app, RevalidatedStaticFiles)
