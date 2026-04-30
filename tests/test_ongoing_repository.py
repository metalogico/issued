import sqlite3

from reader import repository as repo


def _setup_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE folders (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            path TEXT UNIQUE NOT NULL,
            parent_id INTEGER NULL
        );
        CREATE TABLE comics (
            id INTEGER PRIMARY KEY,
            uuid TEXT UNIQUE NOT NULL,
            filename TEXT NOT NULL,
            path TEXT UNIQUE NOT NULL,
            format TEXT NOT NULL,
            file_size INTEGER NOT NULL,
            page_count INTEGER NOT NULL DEFAULT 0,
            file_modified_at TEXT NOT NULL,
            last_scanned_at TEXT NULL,
            created_at TEXT NOT NULL,
            folder_id INTEGER
        );
        CREATE TABLE metadata (
            id INTEGER PRIMARY KEY,
            comic_id INTEGER UNIQUE NOT NULL,
            issue_number INTEGER NULL,
            year INTEGER NULL,
            month INTEGER NULL
        );
        CREATE TABLE ongoing_series (
            folder_id INTEGER PRIMARY KEY,
            marked_at TEXT NOT NULL
        );
        """
    )
    conn.commit()


def test_ongoing_rows_use_filename_fallback_for_gaps():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _setup_schema(conn)

    conn.execute("INSERT INTO folders (id, name, path, parent_id) VALUES (5, 'Series', 'Series', NULL)")
    conn.execute("INSERT INTO ongoing_series (folder_id, marked_at) VALUES (5, '2026-04-29T10:00:00')")

    issue_numbers = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 15]
    for i, num in enumerate(issue_numbers, start=1):
        comic_id = i
        uuid = f"uuid-{i}"
        filename = f"Absolute Batman {num:03d} (2025).cbz"
        conn.execute(
            """
            INSERT INTO comics (id, uuid, filename, path, format, file_size, page_count, file_modified_at, last_scanned_at, created_at, folder_id)
            VALUES (?, ?, ?, ?, 'cbz', 1, 20, '2026-04-29T10:00:00', '2026-04-29T10:00:00', '2026-04-29T10:00:00', 5)
            """,
            (comic_id, uuid, filename, f"Series/{filename}"),
        )
        conn.execute(
            "INSERT INTO metadata (comic_id, issue_number, year, month) VALUES (?, NULL, NULL, NULL)",
            (comic_id,),
        )

    conn.commit()

    rows = repo.list_ongoing_series_rows(conn)
    assert len(rows) == 1
    assert rows[0]["missing_issues"] == [14]


def test_ongoing_rows_expose_last_added_at_when_cover_date_missing():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _setup_schema(conn)

    conn.execute("INSERT INTO folders (id, name, path, parent_id) VALUES (5, 'Series', 'Series', NULL)")
    conn.execute("INSERT INTO ongoing_series (folder_id, marked_at) VALUES (5, '2026-04-29T10:00:00')")
    conn.execute(
        """
        INSERT INTO comics (id, uuid, filename, path, format, file_size, page_count, file_modified_at, last_scanned_at, created_at, folder_id)
        VALUES (1, 'uuid-1', 'Absolute Batman 015 (2026).cbz', 'Series/Absolute Batman 015 (2026).cbz', 'cbz', 1, 20,
                '2026-04-29T10:00:00', '2026-04-30T09:10:30.579677', '2026-04-29T16:10:30.579677', 5)
        """
    )
    conn.execute("INSERT INTO metadata (comic_id, issue_number, year, month) VALUES (1, NULL, NULL, NULL)")
    conn.commit()

    rows = repo.list_ongoing_series_rows(conn)
    assert len(rows) == 1
    assert rows[0]["last_added_at"] == "2026-04-29T16:10:30.579677"
    assert rows[0]["last_issue_number"] == 15


def test_ongoing_rows_ignore_year_and_book_numbers_for_gap_detection():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _setup_schema(conn)

    conn.execute("INSERT INTO folders (id, name, path, parent_id) VALUES (7, 'Age of Revelation', 'Age of Revelation', NULL)")
    conn.execute("INSERT INTO ongoing_series (folder_id, marked_at) VALUES (7, '2026-04-29T10:00:00')")

    filenames = [
        "X-Men - Age of Revelation 000 (2025).cbz",
        "X-Men - Age Of Revelation 001 - Overture (2025).cbz",
        "X-Men - Age Of Revelation 002 - Book of Revelation 1 (2025).cbz",
        "X-Men - Age Of Revelation 002 - Book of Revelation 2 (2026).cbz",
        "X-Men - Age Of Revelation 003 - Book of Revelation 3 (2026).cbz",
        "X-Men - Age of Revelation 005 - Finale (2026).cbz",
    ]
    for idx, filename in enumerate(filenames, start=1):
        conn.execute(
            """
            INSERT INTO comics (id, uuid, filename, path, format, file_size, page_count, file_modified_at, last_scanned_at, created_at, folder_id)
            VALUES (?, ?, ?, ?, 'cbz', 1, 20, '2026-04-29T10:00:00', '2026-04-29T10:00:00', ?, 7)
            """,
            (idx, f"uuid-{idx}", filename, f"Age of Revelation/{filename}", f"2026-04-2{idx}T10:00:00"),
        )
        conn.execute(
            "INSERT INTO metadata (comic_id, issue_number, year, month) VALUES (?, NULL, NULL, NULL)",
            (idx,),
        )
    conn.commit()

    rows = repo.list_ongoing_series_rows(conn)
    assert len(rows) == 1
    assert rows[0]["missing_issues"] == [4]
    assert rows[0]["last_issue_number"] == 5
