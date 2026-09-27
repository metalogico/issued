"""OPDS-PSE contracts, using real page bytes and isolated existing OPDS fixtures."""

import io
import shutil
import subprocess
import zipfile
from datetime import datetime
from unittest.mock import patch
import xml.etree.ElementTree as ET

import pytest
from PIL import Image, features
from sqlmodel import Session

from test_opds import client, test_config, test_db  # noqa: F401
from reader import services
from server.database import db_connection
from server.models import Comic, ComicMetadata, Folder
from server.opds.feeds import PSE_NAMESPACE, PSE_REL, _comic_entry_xml
from server.opds.images import page_as_jpeg

ATOM = '{http://www.w3.org/2005/Atom}'


def image_bytes(fmt='PNG', color='red', mode='RGB', size=(24, 16), **kwargs):
    output = io.BytesIO()
    Image.new(mode, size, color).save(output, format=fmt, **kwargs)
    return output.getvalue()


@pytest.fixture
def book(test_config, test_db, monkeypatch):
    monkeypatch.setattr(services, 'get_config', lambda: test_config)
    monkeypatch.setattr('server.opds.middleware.get_config', lambda: test_config)
    path = test_config.library_path / 'Issue.cbz'
    # Deliberately archive page10 before page2; natural ordering must win.
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('page10.png', image_bytes(color='blue'))
        archive.writestr('page2.png', image_bytes(color='red'))
    with Session(test_db) as session:
        folder = Folder(name='Series & More', path='.')
        session.add(folder)
        session.commit()
        session.refresh(folder)
        comic = Comic(uuid='pse-book', filename=path.name, path=path.name,
                      format='cbz', file_size=path.stat().st_size, page_count=2,
                      file_modified_at=datetime.now(), folder_id=folder.id)
        session.add(comic)
        session.commit()
        session.refresh(comic)
        return path, folder.id, comic.id


def feed_urls(book):
    return [f'/opds/folder/{book[1]}', '/opds/recent', '/opds/search?q=Issue']


def stream_links(response):
    root = ET.fromstring(response.content)
    return root.findall(f"{ATOM}entry/{ATOM}link[@rel='{PSE_REL}']")


def test_pse_all_feeds(client, book):
    with patch.object(services, 'get_archive', side_effect=AssertionError('Feed opened archive')):
        for url in feed_urls(book):
            response = client.get(url)
            assert response.status_code == 200
            assert f'xmlns:pse="{PSE_NAMESPACE}"' in response.text
            links = stream_links(response)
            assert len(links) == 1
            link = links[0]
            assert link.attrib == {
                'rel': PSE_REL, 'type': 'image/jpeg',
                'href': 'http://testserver/opds/comic/pse-book/page/{pageNumber}',
                f'{{{PSE_NAMESPACE}}}count': '2',
            }
            root = ET.fromstring(response.content)
            entry = root.find(f'{ATOM}entry')
            rels = {node.get('rel') for node in entry.findall(f'{ATOM}link')}
            assert {'collection', 'http://opds-spec.org/image/thumbnail',
                    'http://opds-spec.org/acquisition', PSE_REL} <= rels


@pytest.mark.parametrize('count', [None, 0, -1, 1.5, 'unknown', '2', True])
def test_invalid_count_helper(count):
    xml = _comic_entry_xml('id', 'Title & <test>', '2026-01-01T00:00:00Z',
                           'application/x-cbz', 'https://example.com', page_count=count)
    assert PSE_REL not in xml
    assert 'http://opds-spec.org/acquisition' in xml
    ET.fromstring(f'<feed xmlns:pse="{PSE_NAMESPACE}">{xml}</feed>')


@pytest.mark.parametrize('count', [0, -3, 1.5, 'invalid'])
def test_invalid_database_count_omits_link_but_streams(client, book, count):
    with db_connection() as conn:
        conn.execute('UPDATE comics SET page_count=?', (count,))
        conn.commit()
    with patch.object(services, 'get_archive', side_effect=AssertionError('Feed opened archive')):
        for url in feed_urls(book):
            response = client.get(url)
            assert stream_links(response) == []
            assert len(ET.fromstring(response.content).findall(f'{ATOM}entry')) == 1
    with patch.object(services, 'get_archive', wraps=services.get_archive) as opened:
        assert client.get('/opds/comic/pse-book/page/0').status_code == 200
        assert opened.call_count == 1
    with db_connection() as conn:
        assert conn.execute('SELECT page_count FROM comics').fetchone()[0] == count


def test_first_last_and_reader_numbering(client, book):
    for pse_index, reader_index, channel in [(0, 1, 0), (1, 2, 2)]:
        response = client.get(f'/opds/comic/pse-book/page/{pse_index}')
        assert response.status_code == 200
        assert response.headers['content-type'] == 'image/jpeg'
        assert response.headers['cache-control'] == 'private, max-age=3600'
        with Image.open(io.BytesIO(response.content)) as image:
            assert image.format == 'JPEG'
            assert image.size == (24, 16)
            assert image.getpixel((5, 5))[channel] > 245
        original = client.get(f'/reader/api/comic/pse-book/page/{reader_index}')
        assert original.status_code == 200
        assert original.headers['content-type'] == 'image/png'
        with Image.open(io.BytesIO(original.content)) as image:
            assert image.getpixel((5, 5))[channel] == 255
    for index in (0, 3):
        assert client.get(f'/reader/api/comic/pse-book/page/{index}').status_code == 404


@pytest.mark.parametrize(('uuid', 'page', 'status'), [
    ('pse-book', '-1', 404), ('pse-book', '2', 404),
    ('missing', '0', 404), ('pse-book', 'no', 422),
])
def test_page_errors(client, book, uuid, page, status):
    response = client.get(f'/opds/comic/{uuid}/page/{page}')
    assert response.status_code == status
    assert response.headers['content-type'] == 'application/json'
    assert str(book[0]) not in response.text


@pytest.mark.parametrize('failure', ['missing', 'archive', 'image'])
def test_broken_files(client, book, failure):
    path = book[0]
    if failure == 'missing':
        path.unlink()
    elif failure == 'archive':
        path.write_bytes(b'not an archive')
    else:
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('page.png', b'not an image')
    response = client.get('/opds/comic/pse-book/page/0')
    assert response.status_code == (404 if failure == 'missing' else 500)
    assert str(path) not in response.text
    assert response.headers['content-type'] == 'application/json'
    assert 'cache-control' not in response.headers


@pytest.mark.parametrize('dependency', ['python', 'rar'])
def test_missing_backend(client, book, monkeypatch, dependency):
    if dependency == 'rar':
        from server.archive import rarfile
        error = rarfile.RarCannotExec('private/path/unrar')
    else:
        error = ImportError('private/path/backend')
    def unavailable(path):
        raise error
    monkeypatch.setattr(services, 'get_archive', unavailable)
    response = client.get('/opds/comic/pse-book/page/0')
    assert response.status_code == 503
    assert 'private/path' not in response.text
    assert client.get('/reader/api/comic/pse-book/page/1').status_code == 404


@pytest.mark.parametrize('fmt', ['JPEG', 'PNG', 'WEBP'])
def test_actual_bytes_determine_output(client, book, fmt):
    if fmt == 'WEBP' and not features.check('webp'):
        pytest.skip('Pillow WebP codec unavailable')
    data = image_bytes(fmt)
    with zipfile.ZipFile(book[0], 'w') as archive:
        # A misleading extension must not affect PSE output MIME.
        archive.writestr('page.png', data)
    response = client.get('/opds/comic/pse-book/page/0')
    assert response.status_code == 200
    assert response.headers['content-type'] == 'image/jpeg'
    with Image.open(io.BytesIO(response.content)) as image:
        assert image.format == 'JPEG'
        assert image.size == (24, 16)
    if fmt == 'JPEG':
        assert response.content == data
    else:
        assert response.content != data


def test_transparency_orientation_and_first_frame():
    transparent = image_bytes('PNG', (255, 0, 0, 0), 'RGBA')
    with Image.open(io.BytesIO(page_as_jpeg(transparent))) as image:
        assert image.getpixel((0, 0)) == (255, 255, 255)
    exif = Image.Exif()
    exif[274] = 6
    rotated = image_bytes(exif=exif)
    with Image.open(io.BytesIO(page_as_jpeg(rotated))) as image:
        assert image.size == (16, 24)
    animation = io.BytesIO()
    Image.new('RGB', (24, 16), 'red').save(
        animation, format='PNG', save_all=True,
        append_images=[Image.new('RGB', (24, 16), 'blue')], duration=100)
    with Image.open(io.BytesIO(page_as_jpeg(animation.getvalue()))) as image:
        assert image.getpixel((0, 0))[0] > 245
    with pytest.raises(OSError):
        page_as_jpeg(image_bytes('JPEG')[:-20])


@pytest.mark.parametrize('with_progress', [False, True])
def test_streaming_never_writes_progress(client, book, test_db, with_progress):
    if with_progress:
        with Session(test_db) as session:
            session.add(ComicMetadata(comic_id=book[2], current_page=1,
                                      is_completed=True, last_read_at=datetime(2025, 1, 1)))
            session.commit()
    def snapshot():
        with db_connection() as conn:
            return [tuple(row) for row in conn.execute('SELECT * FROM metadata')]
    before = snapshot()
    for page in (1, 0, 0, 1):
        assert client.get(f'/opds/comic/pse-book/page/{page}').status_code == 200
    assert snapshot() == before


def test_reader_auth_does_not_protect_opds(client, book, test_config):
    from server.config import ReaderAuthConfig
    test_config.reader_auth = ReaderAuthConfig(user='reader', password='secret')
    assert client.get('/opds/comic/pse-book/page/0', follow_redirects=False).status_code == 200
    assert client.get('/opds/recent', follow_redirects=False).status_code == 200
    assert client.get('/reader/api/comic/pse-book/page/1', follow_redirects=False).status_code == 302


@pytest.mark.parametrize('fmt', ['cb7', 'pdf', 'cbr'])
def test_real_containers(client, book, tmp_path, fmt):
    path = book[0]  # Intentionally retain .cbz: detection must use content.
    if fmt == 'cb7':
        pytest.importorskip('py7zr')
        from test_cb7_support import _create_cb7
        _create_cb7(path, tmp_path)
    elif fmt == 'pdf':
        fitz = pytest.importorskip('fitz')
        with fitz.open() as doc:
            for color in [(1, 0, 0), (0, 0, 1)]:
                page = doc.new_page(width=24, height=16)
                page.draw_rect(page.rect, color=color, fill=color)
            doc.save(path)
    else:
        rar = shutil.which('rar')
        if not rar:
            pytest.skip('Real CBR fixture generation requires the optional rar executable')
        path.unlink()
        sources = tmp_path / 'rar-pages'
        sources.mkdir()
        for name, color in [('page10.png', 'blue'), ('page2.png', 'red')]:
            (sources / name).write_bytes(image_bytes(color=color))
        subprocess.run([rar, 'a', '-ep', str(path), str(sources / 'page10.png'),
                        str(sources / 'page2.png')], check=True, capture_output=True)
    for page, channel in [(0, 0), (1, 2)]:
        response = client.get(f'/opds/comic/pse-book/page/{page}')
        assert response.status_code == 200
        assert response.headers['content-type'] == 'image/jpeg'
        with Image.open(io.BytesIO(response.content)) as image:
            assert image.format == 'JPEG'
            assert image.getpixel((5, 5))[channel] > 245


def test_cbr_adapter_simulated(client, book, monkeypatch):
    from server import archive as archives
    book[0].write_bytes(archives.RAR5_MAGIC_HEADER)
    class FakeRar:
        def __init__(self, *args, **kwargs):
            pass
        def namelist(self):
            return ['page10.png', 'page2.png']
        def read(self, name):
            return image_bytes(color='red' if name == 'page2.png' else 'blue')
        def close(self):
            pass
    monkeypatch.setattr(archives.rarfile, 'RarFile', FakeRar)
    for page, channel in [(0, 0), (1, 2)]:
        response = client.get(f'/opds/comic/pse-book/page/{page}')
        assert response.status_code == 200
        with Image.open(io.BytesIO(response.content)) as image:
            assert image.getpixel((5, 5))[channel] > 245
