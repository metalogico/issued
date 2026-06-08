"""Archive handling utilities for Issued.

Provides a unified interface for reading CBZ (Zip) and CBR (Rar) archives,
with robust error handling and format fallback detection.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Optional, Protocol, List

try:
    import rarfile
except ImportError:
    rarfile = None

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
PDF_RENDER_DPI = 150  # DPI for rendering PDF pages to images
PDF_MAX_CACHE_PAGES = 50  # Max pages to keep rendered in memory per session


def is_image(filename: str) -> bool:
    return Path(filename).suffix.lower() in IMAGE_EXTENSIONS


class Archive(Protocol):
    def list_images(self) -> List[str]:
        ...

    def list_names(self) -> List[str]:
        """List all file names in the archive (for finding ComicInfo.xml etc.)."""
        ...

    def read(self, filename: str) -> bytes:
        ...

    def close(self) -> None:
        ...

    def __enter__(self) -> "Archive":
        ...

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        ...


class ZipArchiveWrapper:
    def __init__(self, path: Path):
        self.zf = zipfile.ZipFile(path, mode="r")

    def list_images(self) -> List[str]:
        return [n for n in self.zf.namelist() if is_image(n)]

    def list_names(self) -> List[str]:
        return self.zf.namelist()

    def read(self, filename: str) -> bytes:
        return self.zf.read(filename)

    def close(self) -> None:
        self.zf.close()

    def __enter__(self) -> "ZipArchiveWrapper":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()


class RarArchiveWrapper:
    def __init__(self, path: Path):
        if rarfile is None:
            raise ImportError("rarfile module not installed")
        self._path = Path(path)
        self.rf = rarfile.RarFile(path, mode="r")

    def list_images(self) -> List[str]:
        return [n for n in self.rf.namelist() if is_image(n)]

    def list_names(self) -> List[str]:
        return self.rf.namelist()

    def read(self, filename: str) -> bytes:
        try:
            return self.rf.read(filename)
        except rarfile.BadRarFile as exc:
            if "Failed the read enough data" not in str(exc):
                raise
            return self._read_member_via_unrar_cli(filename)

    def _read_member_via_unrar_cli(self, filename: str) -> bytes:
        """When rarfile's pipe-based ``unrar p`` read returns truncated data, extract
        the member with ``unrar e`` into a temp dir and read bytes from disk.
        """
        unrar = getattr(rarfile, "UNRAR_TOOL", None) or "unrar"
        arch = os.fspath(self._path)
        internal = filename.replace("/", os.path.sep)
        tmp = tempfile.mkdtemp(prefix="issued_cbr_")
        try:
            cmd = [
                unrar,
                "e",
                "-o+",
                "-inul",
                "-p-",
                arch,
                internal,
            ]
            proc = subprocess.run(
                cmd,
                cwd=tmp,
                capture_output=True,
                timeout=600,
                check=False,
            )
            if proc.returncode != 0:
                err = (proc.stderr or b"").decode(errors="replace")[:500]
                raise rarfile.BadRarFile(
                    f"unrar e failed (exit {proc.returncode}) for {filename!r}: {err}"
                ) from None
            base = os.path.basename(internal.replace("\\", "/"))
            out_path = os.path.join(tmp, base)
            if not os.path.isfile(out_path):
                raise rarfile.BadRarFile(
                    f"unrar e succeeded but {base!r} missing in temp dir (member {filename!r})"
                )
            with open(out_path, "rb") as handle:
                return handle.read()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def close(self) -> None:
        self.rf.close()

    def __enter__(self) -> "RarArchiveWrapper":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()


class PdfBookWrapper:
    """Wrapper for PDF books that exposes pages as images via Archive protocol.

    PDFs are books/documents, not archives, but implement the Archive interface
    for compatibility with the comic library system. Pages are rendered to PNG
    format on-demand at configured DPI. Page names are synthetic (page_001.png,
    page_002.png, ...).
    """

    def __init__(self, path: Path, dpi: int = PDF_RENDER_DPI):
        if fitz is None:
            raise ImportError("PyMuPDF (fitz) module not installed")
        self._path = Path(path)
        self._dpi = dpi
        try:
            self._doc = fitz.open(path)
        except Exception as exc:
            raise ValueError(f"Cannot open PDF {path.name}: {exc}")

        # Pre-compute synthetic page names (4-digit zero-padding supports up to 9999 pages)
        self._page_names = [
            f"page_{i+1:04d}.png" for i in range(len(self._doc))
        ]
        self._image_cache: dict[str, bytes] = {}  # LRU-bounded cache (max PDF_MAX_CACHE_PAGES entries)

    def list_images(self) -> List[str]:
        """Return synthetic page names as image list."""
        return self._page_names.copy()

    def list_names(self) -> List[str]:
        """Return all names including synthetic ComicInfo.xml if metadata present."""
        names = self._page_names.copy()
        # PDFs often have metadata; expose as ComicInfo.xml for compatibility.
        # fitz always returns a dict with all keys present, so check for any non-empty value.
        if any(self._doc.metadata.values()):
            names.append("ComicInfo.xml")
        return names

    def read(self, filename: str) -> bytes:
        """Render PDF page to PNG bytes or return cached result."""
        if filename == "ComicInfo.xml":
            return self._generate_comicinfo_xml()

        if filename not in self._page_names:
            raise KeyError(f"Page {filename} not found in PDF")

        # Check cache first
        if filename in self._image_cache:
            return self._image_cache[filename]

        # Extract page number from synthetic name (page_001.png -> 0)
        page_idx = self._page_names.index(filename)

        try:
            page = self._doc[page_idx]
            # Render page to pixmap at specified DPI
            mat = fitz.Matrix(self._dpi / 72, self._dpi / 72)
            pix = page.get_pixmap(matrix=mat)

            # Convert pixmap to PNG bytes
            img_bytes = pix.tobytes("png")

            # Cache for this session (evict oldest entry when limit reached)
            if len(self._image_cache) >= PDF_MAX_CACHE_PAGES:
                self._image_cache.pop(next(iter(self._image_cache)))
            self._image_cache[filename] = img_bytes
            return img_bytes

        except Exception as exc:
            raise IOError(f"Failed to render page {page_idx} from {self._path.name}: {exc}")

    def _generate_comicinfo_xml(self) -> bytes:
        """Generate basic ComicInfo.xml from PDF metadata."""
        meta = self._doc.metadata
        title = meta.get("title", "") or self._path.stem
        author = meta.get("author", "")

        # Basic ComicInfo structure
        xml_parts = ['<?xml version="1.0"?>', '<ComicInfo>']
        if title:
            xml_parts.append(f'  <Title>{_escape_xml_content(title)}</Title>')
        if author:
            xml_parts.append(f'  <Writer>{_escape_xml_content(author)}</Writer>')
        xml_parts.append(f'  <PageCount>{len(self._doc)}</PageCount>')
        xml_parts.append('</ComicInfo>')

        return '\n'.join(xml_parts).encode('utf-8')

    def close(self) -> None:
        """Close PDF document and clear cache."""
        self._image_cache.clear()
        if self._doc:
            self._doc.close()

    def __enter__(self) -> "PdfBookWrapper":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()


def _escape_xml_content(s: str) -> str:
    """Escape XML special characters in content."""
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def configure_rar_tool(tool_path: str) -> None:
    """Set the unrar/rar executable path used by rarfile."""
    if rarfile is not None:
        rarfile.UNRAR_TOOL = tool_path


def get_archive(path: Path) -> Archive:
    """Open a comic book file (archive or PDF), detecting format by extension.

    Tries the expected format first (cbz→zip, cbr→rar, pdf→book).
    If that fails for cbz/cbr, tries the other format (handles misnamed files).
    """
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    suffix = path.suffix.lower()

    # PDF: direct book wrapper, no fallback needed
    if suffix == ".pdf":
        return PdfBookWrapper(path)

    # Existing CBZ/CBR logic with fallback
    if suffix == ".cbz":
        primary, fallback = ZipArchiveWrapper, RarArchiveWrapper
    elif suffix == ".cbr":
        primary, fallback = RarArchiveWrapper, ZipArchiveWrapper
    else:
        raise ValueError(f"Unsupported archive format: {suffix}")

    primary_exc: Optional[Exception] = None
    try:
        return primary(path)
    except Exception as exc:
        primary_exc = exc

    try:
        return fallback(path)
    except Exception as fallback_exc:
        raise ValueError(
            f"Cannot open {path.name} as {primary.__name__} ({primary_exc}) "
            f"or {fallback.__name__} ({fallback_exc})"
        ) from fallback_exc
