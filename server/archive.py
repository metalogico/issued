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


def configure_rar_tool(tool_path: str) -> None:
    """Set the unrar/rar executable path used by rarfile."""
    if rarfile is not None:
        rarfile.UNRAR_TOOL = tool_path


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
