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


def _navigation_entry_xml(
    entry_id: str,
    title: str,
    target_path: str,
    updated_ts: str,
    base_url: str,
    *,
    thumbnail_uuid: Optional[str] = None,
) -> str:
    """Build a navigation entry with optional artwork for capable OPDS clients."""
    thumbnail_link = ""
    if thumbnail_uuid:
        thumbnail_link = (
            '\n    <link rel="http://opds-spec.org/image/thumbnail"'
            f' href="{_absolute_href(base_url, _comic_thumb_href(thumbnail_uuid))}"'
            ' type="image/webp" />'
        )

    return f"""
  <entry>
    <title>{_escape_xml(title)}</title>
    <id>{_escape_xml(entry_id)}</id>
    <updated>{updated_ts}</updated>{thumbnail_link}
    <link rel="subsection"
          href="{_absolute_href(base_url, target_path)}"
          type="application/atom+xml;profile=opds-catalog" />
  </entry>"""


def _folder_entry_xml(
    folder_id: int,
    title: str,
    updated_ts: str,
    base_url: str,
    *,
    thumbnail_uuid: Optional[str] = None,
) -> str:
    return _navigation_entry_xml(
        f"urn:folder:{folder_id}",
        title,
        _folder_href(folder_id),
        updated_ts,
        base_url,
        thumbnail_uuid=thumbnail_uuid,
    )


def _recent_href(limit: int) -> str:
    return f"/opds/recent?limit={limit}"


def _search_href(q: str) -> str:
    return f"/opds/search?q={quote(q)}"


def _opensearch_href() -> str:
    return "/opds/search.xml"


def _search_template_href() -> str:
    return "/opds/search?q={searchTerms}"


def _absolute_href(base_url: str, path: str) -> str:
    return base_url.rstrip("/") + path


def _catalog_links_xml(base_url: str, self_href: str) -> str:
    """Atom catalog links: self, start, and OpenSearch autodiscovery."""
    start_href = _absolute_href(base_url, _root_href())
    search_href = _absolute_href(base_url, _opensearch_href())
    return (
        f'  <link rel="self" href="{self_href}" type="application/atom+xml;profile=opds-catalog" />\n'
        f'  <link rel="start" href="{start_href}" type="application/atom+xml;profile=opds-catalog" />\n'
        f'  <link rel="search" href="{search_href}" type="application/opensearchdescription+xml" />'
    )


def _opensearch_short_name(library_title: str) -> str:
    """OpenSearch ShortName is limited to 16 plain-text characters."""
    name = library_title.strip()
    if not name:
        return "Issued"
    return name[:16]


def _opensearch_description_xml(base_url: str, library_title: str) -> str:
    title = library_title.strip() or "Issued Library"
    short_name = _escape_xml(_opensearch_short_name(title))
    description = _escape_xml(f"Search {title}")
    template = _absolute_href(base_url, _search_template_href())
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<OpenSearchDescription xmlns="http://a9.com/-/spec/opensearch/1.1/">\n'
        f"  <ShortName>{short_name}</ShortName>\n"
        f"  <Description>{description}</Description>\n"
        "  <InputEncoding>UTF-8</InputEncoding>\n"
        '  <Url type="application/atom+xml;profile=opds-catalog;kind=acquisition"\n'
        f'       template="{template}" />\n'
        "</OpenSearchDescription>"
    )


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
    if fmt_lower == "cb7":
        return "application/x-7z-compressed"
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


def _opensearch_response(xml: str) -> Response:
    return Response(
        content=xml,
        media_type="application/opensearchdescription+xml",
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
