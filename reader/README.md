# Web Reader

Simple web UI for browsing and reading comics from the Issued library.

Supports CBZ, CBR, CB7, and PDF formats with automatic page extraction and rendering.

## Structure

- **`routes/`** – FastAPI router: browse (root, folder, recent), reader view, API for comic info and page images.
- **`services.py`** – Logic: comic lookup by UUID, page image extraction from archives/PDFs (uses `server`).
- **`templates/`** – Jinja2 HTML: `base.html`, `browser.html`, `reader.html`.
- **`static/`** – CSS and JS: `css/style.css`, `js/reader.js`.

## Routes

- `GET /reader` – Browse root (folders + recent link).
- `GET /reader/recent` – Recent comics.
- `GET /reader/folder/{id}` – Browse folder (subfolders + comics).
- `GET /reader/comic/{uuid}` – Reader: open comic and flip pages.
- `GET /reader/api/comic/{uuid}` – JSON: title, page_count.
- `GET /reader/api/comic/{uuid}/page/{n}` – Image for page `n` (1-based).

## Dependencies

- **Jinja2** – templates (in `requirements.txt`).
- **Issued `server`** – config, database, path_utils, archive.

## OPDS page streaming

OPDS-PSE 1.2 uses `GET /opds/comic/{uuid}/page/{n}` with **0-based** numbering.
It shares the archive extraction service with this reader but always returns
JPEG (original JPEGs are preserved; other images are converted without resizing).
The internal extraction index is also 0-based; the web reader route subtracts
one from its public 1-based page number.

Like the existing OPDS catalog, this endpoint does not require the reader login
cookie, even when reader authentication is enabled. It does not save progress,
completion, or last-read dates. Progress is saved separately through Issued's
existing progress APIs. See the main README for feed counts, errors, caching,
and reverse proxy configuration.
