"""OPDS Atom feed XML helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote

from fastapi import Response

from ..config import IssuedConfig


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _root_href() -> str:
    return "/opds/"


def _folder_href(folder_id: int) -> str:
    return f"/opds/folder/{folder_id}"


def _comic_file_href(comic_uuid: str) -> str:
    return f"/opds/comic/{comic_uuid}/file"


def _comic_thumb_href(comic_uuid: str) -> str:
    return f"/opds/comic/{comic_uuid}/thumbnail"


def _recent_href(limit: int) -> str:
    return f"/opds/recent?limit={limit}"


def _search_href(q: str) -> str:
    return f"/opds/search?q={quote(q)}"


def _absolute_href(base_url: str, path: str) -> str:
    return base_url.rstrip("/") + path


def _escape_xml(s: str) -> str:
    """Escape &, <, >, ", ' for XML text/attributes."""
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _comic_media_type(fmt: str) -> str:
    """Return the MIME type for a comic format string (e.g. 'cbz', 'pdf')."""
    fmt_lower = fmt.lower()
    if fmt_lower == "cbz":
        return "application/x-cbz"
    if fmt_lower == "cbr":
        return "application/x-cbr"
    if fmt_lower == "pdf":
        return "application/pdf"
    return "application/octet-stream"


def _get_library_title(config: IssuedConfig | None) -> str:
    if config is None:
        return "Issued Library"
    return config.library.name


def _xml_response(xml: str) -> Response:
    return Response(
        content=xml,
        media_type="application/atom+xml;profile=opds-catalog",
    )


def _comic_entry_xml(
    comic_uuid: str,
    title: str,
    updated_ts: str,
    media_type: str,
    base_url: str,
    *,
    series_folder_id: Optional[int] = None,
    series_name: Optional[str] = None,
) -> str:
    """Build OPDS entry XML for a comic. Adds rel=collection when folder is a series (leaf)."""
    links = [
        f'    <link rel="http://opds-spec.org/image/thumbnail"'
        f'          href="{_absolute_href(base_url, _comic_thumb_href(comic_uuid))}" type="image/webp" />',
        f'    <link rel="http://opds-spec.org/acquisition"'
        f'          href="{_absolute_href(base_url, _comic_file_href(comic_uuid))}" type="{media_type}" />',
    ]
    if series_folder_id is not None and series_name is not None:
        links.insert(
            1,
            f'    <link rel="collection"'
            f'          href="{_absolute_href(base_url, _folder_href(series_folder_id))}"'
            f'          type="application/atom+xml;profile=opds-catalog;kind=acquisition"'
            f'          title="{_escape_xml(series_name)}" />',
        )
    links_str = "\n".join(links)
    return f"""
  <entry>
    <title>{_escape_xml(title)}</title>
    <id>urn:comic:{comic_uuid}</id>
    <updated>{updated_ts}</updated>
{links_str}
  </entry>"""
