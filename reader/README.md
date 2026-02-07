# Web Reader

Simple web UI for browsing and reading comics from the Issued library.

## Structure

- **`router.py`** – FastAPI router: browse (root, folder, recent), reader view, API for comic info and page images.
- **`services.py`** – Logic: comic lookup by UUID, page image extraction from archives (uses `src`).
- **`templates/`** – Jinja2 HTML: `base.html`, `browser.html`, `reader.html`.
- **`static/`** – CSS and JS: `css/style.css`, `js/reader.js`.

## Routes

- `GET /reader` – Browse root (folders + recent link).
- `GET /reader/recent` – Recent comics.
- `GET /reader/folder/{id}` – Browse folder (subfolders + comics).
- `GET /reader/comic/{uuid}` – Reader: open comic and flip pages.
- `GET /reader/api/comic/{uuid}` – JSON: title, page_count.
- `GET /reader/api/comic/{uuid}/page/{n}` – Image for page `n` (0-based).

## Dependencies

- **Jinja2** – templates (in `requirements.txt`).
- **Issued `src`** – config, database, path_utils, archive.
