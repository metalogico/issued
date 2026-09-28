"""Folder navigation hierarchy and opt-in page rendering."""
import sqlite3

from reader.repo.folders import get_navigation_tree
from test_continue_series import continue_series_app  # noqa: F401


def test_tree_single_query_order_selection_and_single_root():
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.execute('CREATE TABLE folders (id INTEGER PRIMARY KEY, name TEXT, parent_id INTEGER)')
    conn.executemany('INSERT INTO folders VALUES (?, ?, ?)', [
        (1, 'Library', None), (2, 'Marvel', 1), (3, 'DC', 1),
        (4, 'Series', 2), (5, 'Series', 3), (6, '<Long & name>', 4),
    ])
    queries = []
    conn.set_trace_callback(queries.append)
    tree = get_navigation_tree(conn, 6)
    assert len(queries) == 1
    assert [n['name'] for n in tree['nodes']] == ['DC', 'Marvel']
    assert tree['nodes'][1]['children'][0]['children'][0]['id'] == 6
    assert tree['ancestors'] == [4, 2, 1]
    assert tree['selected_id'] == 6
    assert not tree['home_active']
    assert get_navigation_tree(conn, 1)['home_active']
    assert get_navigation_tree(conn)['home_active']
    conn.execute("INSERT INTO folders VALUES (7, 'Other root', NULL)")
    assert [n['id'] for n in get_navigation_tree(conn)['nodes']] == [1, 7]
    conn.execute('DELETE FROM folders')
    assert get_navigation_tree(conn)['nodes'] == []


def test_tree_only_on_home_and_folders(continue_series_app):
    folder_id, client = continue_series_app
    for path in ['/reader/', f'/reader/folder/{folder_id}']:
        response = client.get(path)
        assert response.status_code == 200
        assert 'id="show-tree-toggle"' in response.text
        assert 'id="folder-tree-panel"' in response.text
        assert 'folder-tree.js' in response.text
        assert 'class="folder-tree-home" href="/reader/" aria-current="page"' in response.text
    for path in ['/reader/search?q=series', '/reader/recent', '/reader/tags',
                 '/reader/tags/test', '/reader/ongoings', '/reader/comic/issue-1']:
        response = client.get(path)
        assert response.status_code == 200
        assert 'id="show-tree-toggle"' not in response.text
        assert 'id="folder-tree-panel"' not in response.text
        assert 'folder-tree.js' not in response.text


def test_nested_page_renders_ancestors_links_and_escaped_names(continue_series_app):
    folder_id, client = continue_series_app
    from server.database import db_connection
    with db_connection() as conn:
        conn.execute('INSERT INTO folders (id,name,path,parent_id,created_at) VALUES (20,?, ?, ?, ?)',
                     ('<Marvel>', 'Marvel', folder_id, '2026-09-28'))
        conn.execute("INSERT INTO folders (id,name,path,parent_id,created_at) VALUES (21,'Series','Marvel/Series',20,'2026-09-28')")
        conn.commit()
    response = client.get('/reader/folder/21')
    assert response.status_code == 200
    assert '&lt;Marvel&gt;' in response.text
    assert 'data-folder-toggle="20"' in response.text
    assert 'id="folder-children-20" hidden' not in response.text
    assert 'href="/reader/folder/21" data-tree-folder="21"\n        aria-current="page"' in response.text
    assert 'data-folder-toggle="21"' not in response.text
