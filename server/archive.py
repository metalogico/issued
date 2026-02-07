"""Archive handling utilities for Issued.

Provides a unified interface for reading CBZ (Zip) and CBR (Rar) archives,
with robust error handling and format fallback detection.
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Protocol, List

try:
    import rarfile
except ImportError:
    rarfile = None


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


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
        self.rf = rarfile.RarFile(path, mode="r")

    def list_images(self) -> List[str]:
        return [n for n in self.rf.namelist() if is_image(n)]

    def list_names(self) -> List[str]:
        return self.rf.namelist()

    def read(self, filename: str) -> bytes:
        return self.rf.read(filename)

    def close(self) -> None:
        self.rf.close()

    def __enter__(self) -> "RarArchiveWrapper":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()


def get_archive(path: Path) -> Archive:
    """Open an archive, detecting format by extension with fallback.

    Tries the expected format first (cbz→zip, cbr→rar).
    If that fails, tries the other format (handles misnamed files).
    """
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    suffix = path.suffix.lower()
    if suffix == ".cbz":
        primary, fallback = ZipArchiveWrapper, RarArchiveWrapper
    elif suffix == ".cbr":
        primary, fallback = RarArchiveWrapper, ZipArchiveWrapper
    else:
        raise ValueError(f"Unsupported archive format: {suffix}")

    try:
        return primary(path)
    except Exception:
        pass

    return fallback(path)
