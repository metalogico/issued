"""ComicInfo.xml parsing for Issued.

Reads ComicInfo.xml from inside CBZ/CBR archives and extracts metadata.
The <Series> tag is never used; series is set from the folder name when the folder is a leaf.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

from .archive import get_archive

# ComicInfo tag names (case-insensitive in XML). Series excluded.
TAG_MAP = {
    "title": "title",
    "writer": "writer",
    "penciller": "penciller",
    "issue": "issue_number",
    "month": "month",
    "year": "year",
    "notes": "notes",
    "summary": "summary",
    "web": "web",
    "languageiso": "language_iso",
    "genre": "genre",
    "publisher": "publisher",
}


class ComicInfoParsed(BaseModel):
    """Metadata parsed from ComicInfo.xml (all optional)."""

    model_config = {"extra": "ignore"}

    title: Optional[str] = None
    issue_number: Optional[int] = None
    publisher: Optional[str] = None
    year: Optional[int] = None
    month: Optional[int] = None
    writer: Optional[str] = None
    penciller: Optional[str] = None
    summary: Optional[str] = None
    notes: Optional[str] = None
    web: Optional[str] = None
    language_iso: Optional[str] = None
    genre: Optional[str] = None


class ComicMetadataUpdate(BaseModel):
    """Payload for updating comic metadata: ComicInfo fields + series (from folder when leaf)."""

    model_config = {"extra": "ignore"}

    series: Optional[str] = None
    title: Optional[str] = None
    issue_number: Optional[int] = None
    publisher: Optional[str] = None
    year: Optional[int] = None
    month: Optional[int] = None
    writer: Optional[str] = None
    penciller: Optional[str] = None
    summary: Optional[str] = None
    notes: Optional[str] = None
    web: Optional[str] = None
    language_iso: Optional[str] = None
    genre: Optional[str] = None


def _text(elem: Optional[ET.Element]) -> Optional[str]:
    if elem is None or elem.text is None:
        return None
    t = elem.text.strip()
    return t or None


def _int_or_none(s: Optional[str]) -> Optional[int]:
    if s is None:
        return None
    try:
        return int(s.strip())
    except ValueError:
        return None


def _local_name(tag: str) -> str:
    """Return tag without namespace (e.g. '{http://...}Issue' -> 'issue')."""
    return tag.split("}")[-1].lower() if "}" in tag else tag.lower()


def parse_comicinfo_xml(xml_bytes: bytes) -> ComicInfoParsed:
    """Parse ComicInfo.xml content into a validated Pydantic model. <Series> is ignored."""
    raw: dict[str, object] = {}
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return ComicInfoParsed()

    by_lower = {_local_name(elem.tag): elem for elem in root}

    for xml_tag_lower, our_key in TAG_MAP.items():
        elem = by_lower.get(xml_tag_lower)
        text = _text(elem) if elem is not None else None
        if text is None:
            continue
        if our_key in ("issue_number", "month", "year"):
            val = _int_or_none(text)
            if val is not None:
                raw[our_key] = val
        else:
            raw[our_key] = text

    return ComicInfoParsed.model_validate(raw)


def read_comicinfo_from_archive(archive_path: Path) -> Optional[ComicInfoParsed]:
    """Read ComicInfo.xml from a comic archive (CBZ/CBR) and return parsed model, or None."""
    try:
        with get_archive(archive_path) as archive:
            names = archive.list_names()
            comicinfo_name = next(
                (n for n in names if Path(n).name.lower() == "comicinfo.xml"),
                None,
            )
            if comicinfo_name is None:
                return None
            raw = archive.read(comicinfo_name)
    except Exception:
        return None

    if not raw.strip():
        return None
    return parse_comicinfo_xml(raw)
