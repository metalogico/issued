"""Filesystem scanner for Issued.

Responsible for syncing the filesystem state into the SQLite database.

Implements:
- initial full scan
- incremental scan based on file mtime
- folder/comic bookkeeping in SQLite
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator, Optional, Tuple

from .config import IssuedConfig
from .database import get_engine, init_db
from .logging_config import get_logger
from .repository import Repository
from .thumbnails import generate_thumbnail_for_comic
from .comicinfo import read_comicinfo_from_archive, ComicMetadataUpdate
from .utils import delete_thumbnails, short_path
from sqlmodel import Session

logger = get_logger(__name__)


COMIC_EXTENSIONS = {".cbz", ".cbr"}


def is_comic_file(path: Path) -> bool:
    """Return True if the path looks like a supported comic archive."""
    return path.suffix.lower() in COMIC_EXTENSIONS


def _should_ignore(name: str, ignore_patterns: Iterable[str]) -> bool:
    """Check if file/folder should be ignored based on patterns or macOS temp files."""
    # Skip macOS temporary/metadata files (._*)
    if name.startswith("._"):
        return True
    return name in ignore_patterns


def walk_library(
    root: Path,
    ignore_patterns: Tuple[str, ...],
) -> Iterator[Tuple[Path, Iterable[Path]]]:
    """Yield (directory, comic_files) under root, respecting ignore patterns."""
    root = root.resolve()
    for dirpath, dirnames, filenames in os.walk(root):
        dir_path = Path(dirpath)

        # Filter out ignored directories in-place so os.walk doesn't descend
        dirnames[:] = [
            d for d in dirnames if not _should_ignore(d, ignore_patterns)
        ]

        comic_files = [
            dir_path / f
            for f in filenames
            if not _should_ignore(f, ignore_patterns)
            and is_comic_file(Path(f))
        ]
        yield dir_path, comic_files


def validate_and_count_pages(path: Path) -> int:
    """Validate archive integrity and return page count.

    Raises Exception (e.g. BadZipFile) if archive is corrupt.
    """
    from .archive import get_archive

    # Let get_archive raise exceptions if file is bad/corrupt
    with get_archive(path) as archive:
        images = archive.list_images()
        return len(images)


def _should_skip_comic(comic_in_db, file_mtime: datetime, force: bool) -> bool:
    """Check if comic should be skipped based on mtime and metadata presence.
    
    Skip if:
    - Comic exists in DB
    - File mtime hasn't changed
    - Metadata row exists (even if empty - means it was already processed)
    - force=False
    
    Don't skip if:
    - force=True (explicit re-scan requested)
    - Comic not in DB (new file)
    - File mtime changed (file was modified/replaced)
    - No metadata row (first-time processing needed)
    """
    if force or not comic_in_db:
        return False
    
    if not comic_in_db.file_modified_at:
        return False
    
    # If mtime changed, don't skip (file was modified)
    if comic_in_db.file_modified_at != file_mtime:
        return False
    
    # If no metadata row exists, don't skip (first-time processing)
    if not comic_in_db.metadata_rel:
        return False
    
    # Comic unchanged and already processed (metadata row exists), skip it
    return True


def process_comic(
    comic_path: Path,
    folder_id: int,
    config: IssuedConfig,
    repo: Repository,
    force: bool,
) -> tuple[Optional[int], bool, bool, bool]:
    """Process a single comic file.
    
    Returns: (comic_uuid, was_existing, should_skip, thumbnail_generated)
    """
    try:
        stat = comic_path.stat()
    except (FileNotFoundError, PermissionError) as exc:
        logger.error(f"✗ {comic_path.name} - Unable to stat: {exc}")
        return None, False, True, False

    file_mtime = datetime.fromtimestamp(stat.st_mtime)
    file_size = stat.st_size

    # Check if comic exists and should be skipped
    comic_in_db = repo.get_comic_by_path(comic_path)
    existing = comic_in_db is not None

    if _should_skip_comic(comic_in_db, file_mtime, force):
        return None, existing, True, False

    # Validate and count pages
    try:
        page_count = validate_and_count_pages(comic_path)
    except Exception as exc:
        logger.error(f"✗ {comic_path.name} - CORRUPT: {exc}")
        
        if existing:
            deleted_uuids = repo.delete_comic_by_path(comic_path)
            repo.commit()
            if deleted_uuids:
                delete_thumbnails(deleted_uuids, config.thumbnails_dir)

        return None, existing, True, False

    # Process comic
    fmt = comic_path.suffix.lower().lstrip(".")

    # Use existing thumbnail status if updating, else False
    thumb_gen = comic_in_db.thumbnail_generated if comic_in_db else False

    comic = repo.upsert_comic(
        folder_id=folder_id,
        path=comic_path,
        filename=comic_path.name,
        fmt=fmt,
        file_size=file_size,
        page_count=page_count,
        file_modified_at=file_mtime,
        thumbnail_generated=thumb_gen,
    )

    # Generate thumbnail
    thumb_success = generate_thumbnail_for_comic(comic.uuid, comic_path, config, repo)

    # ComicInfo.xml metadata: parse when available; series from folder name only when leaf (never from ComicInfo <Series>)
    comicinfo = read_comicinfo_from_archive(comic_path)
    is_leaf = not repo.folder_has_subfolders(folder_id)
    series_from_folder = comic_path.parent.name if is_leaf else None
    
    # Check if ComicInfo has actual data (not just an empty model)
    comicinfo_fields = comicinfo.model_dump(exclude_none=True) if comicinfo else {}
    
    if comicinfo_fields:
        # Has ComicInfo data
        payload = ComicMetadataUpdate(
            series=series_from_folder,
            **comicinfo_fields,
        )
        repo.update_comic_metadata(comic.id, payload)
    elif series_from_folder is not None:
        # No ComicInfo, but set series from folder name
        repo.update_comic_metadata(comic.id, ComicMetadataUpdate(series=series_from_folder))

    repo.commit()

    # Log with inline status
    thumb_status = "✓" if thumb_success else "✗"
    logger.debug(f"{thumb_status} {comic_path.name} ({page_count} pages)")

    return comic.uuid, existing, False, thumb_success


def scan_file(path: Path, config: IssuedConfig) -> None:
    """Scan a single comic file.
    
    Handles DB session and folder creation internally.
    """
    if not path.exists():
        return

    with Session(get_engine()) as session:
        repo = Repository(session, config.library_path)
        
        # Get/Create folder for this file
        folder = repo.get_or_create_folder(path.parent)
        
        process_comic(
            path, folder.id, config, repo, force=False
        )


def scan_folder(
    path: Path,
    config: IssuedConfig,
) -> None:
    """Scan a specific folder for new comics.
    
    Used by the monitor to process new folders sequentially.
    """
    if not path.exists() or not path.is_dir():
        return

    comic_files = []
    for root, dirs, files in os.walk(path):
        for file in files:
            file_path = Path(root) / file
            if is_comic_file(file_path) and not file_path.name.startswith("._"):
                comic_files.append(file_path)
    
    if comic_files:
        rel_path = path.relative_to(config.library_path)
        logger.info(f"[+] New folder: {rel_path} ({len(comic_files)} files)")
        
        with Session(get_engine()) as session:
            repo = Repository(session, config.library_path)
            
            for comic_path in comic_files:
                folder = repo.get_or_create_folder(comic_path.parent)
                
                process_comic(
                    comic_path, folder.id, config, repo, force=False
                )


def delete_path(path: Path, config: IssuedConfig) -> None:
    """Delete a file or folder from the database and remove thumbnails."""
    with Session(get_engine()) as session:
        repo = Repository(session, config.library_path)
        try:
            if path.is_dir() or (not path.exists() and path.suffix not in COMIC_EXTENSIONS):
                # It's a folder (or was a folder)
                comic_uuids = repo.delete_comics_under_path(path)
                repo.delete_folder_by_path(path)
                repo.commit()

                if comic_uuids:
                    delete_thumbnails(comic_uuids, config.thumbnails_dir)

                rel_path = path.relative_to(config.library_path)
                logger.info(f"[-] Removed folder: {rel_path} ({len(comic_uuids)} comics)")

            else:
                # It's a file
                comic_uuids = repo.delete_comic_by_path(path)
                repo.commit()

                if comic_uuids:
                    delete_thumbnails(comic_uuids, config.thumbnails_dir)
                
                logger.info(f"[-] Removed: {path.name}")
                
        except Exception as e:
            logger.error(f"✗ Failed to delete {path.name}: {e}")


def move_path(src_path: Path, dest_path: Path, config: IssuedConfig) -> None:
    """Handle file or folder move/rename in the database."""
    with Session(get_engine()) as session:
        repo = Repository(session, config.library_path)
        try:
            is_folder = False
            if dest_path.exists():
                is_folder = dest_path.is_dir()
            else:
                # Fallback heuristic
                is_folder = src_path.suffix not in COMIC_EXTENSIONS
            
            if is_folder:
                # Folder moved
                dest_parent = dest_path.parent
                base_path = config.library_path
                
                if dest_parent != base_path:
                    repo.get_or_create_folder(dest_parent)
                
                repo.update_folder_path(src_path, dest_path)
                repo.update_comic_paths(src_path, dest_path)
                repo.commit()
                
                dest_rel = dest_path.relative_to(base_path)
                logger.info(f"[→] Moved folder: {src_path.name} → {dest_rel}")
                
            else:
                # File moved
                if not is_comic_file(dest_path):
                    return

                comic = repo.get_comic_by_path(src_path)
                if comic:
                    from .path_utils import to_relative
                    new_folder_path = dest_path.parent
                    folder = repo.get_or_create_folder(new_folder_path)
                    
                    comic.path = to_relative(dest_path, config.library_path)
                    comic.folder_id = folder.id
                    comic.filename = dest_path.name
                    session.add(comic)
                    repo.commit()

                    logger.info(f"[→] Moved: {src_path.name} → {dest_path.name}")
                else:
                    # Treat as new if not found
                    process_comic(dest_path, repo.get_or_create_folder(dest_path.parent).id, config, repo, False)

        except Exception as e:
            logger.error(f"✗ Failed to move {src_path.name}: {e}")


def scan_library(
    config: IssuedConfig,
    path: Optional[Path] = None,
    force: bool = False,
) -> dict:
    """Scan the comic library and sync to the database.

    :param config: Loaded Issued configuration.
    :param path: Optional subfolder to limit scan.
    :param force: If True, ignore incremental optimizations.
    :return: Dictionary with scan statistics (added, updated, deleted, skipped).
    """
    base = (path or config.library_path).resolve()
    if not base.exists():
        raise FileNotFoundError(f"Library path does not exist: {base}")

    ignore_patterns = tuple(config.scanner.ignore_patterns)
    library_root = config.library_path.resolve()

    stats = {"added": 0, "updated": 0, "deleted": 0, "skipped": 0}
    processed_paths: set[Path] = set()

    # Ensure DB is initialized (schema created)
    init_db()

    with Session(get_engine()) as session:
        repo = Repository(session, config.library_path)
        
        for dir_path, comic_files in walk_library(base, ignore_patterns):
            # Create folder entry
            folder = repo.get_or_create_folder(dir_path)
            
            # Log folder being scanned
            rel_folder = dir_path.relative_to(library_root) if dir_path != library_root else Path(".")
            folder_display = str(rel_folder) if str(rel_folder) != "." else "root"
            logger.info(f"[SCAN] {folder_display} ({len(comic_files)} files)")

            for comic_path in comic_files:
                processed_paths.add(comic_path.resolve())
                
                comic_uuid, was_existing, should_skip, thumb_gen = process_comic(
                    comic_path, folder.id, config, repo, force
                )
                
                if should_skip:
                    stats["skipped"] += 1
                elif was_existing:
                    stats["updated"] += 1
                else:
                    stats["added"] += 1

        # Handle deleted files
        # Comics in DB under 'base' that were not processed and don't exist on disk
        from sqlmodel import select, col
        from .models import Comic, Folder
        from .path_utils import to_relative, to_absolute

        base_rel_str = to_relative(base, library_root).rstrip("/")

        if base == library_root:
            statement = select(Comic)
        else:
            statement = select(Comic).where(col(Comic.path).like(f"{base_rel_str}/%"))

        db_comics = session.exec(statement).all()

        for comic in db_comics:
            comic_abs_path = to_absolute(comic.path, library_root)

            if comic_abs_path not in processed_paths and not comic_abs_path.exists():
                deleted_uuids = repo.delete_comic_by_path(comic_abs_path)
                repo.commit()
                if deleted_uuids:
                    delete_thumbnails(deleted_uuids, config.thumbnails_dir)
                stats["deleted"] += 1

        # Handle deleted folders: remove from DB any folder under 'base' that no longer exists on disk
        if base == library_root:
            folder_statement = select(Folder)
        else:
            folder_statement = select(Folder).where(
                (Folder.path == base_rel_str) | (col(Folder.path).like(f"{base_rel_str}/%"))
            )
        db_folders = session.exec(folder_statement).all()

        for folder in db_folders:
            folder_abs_path = to_absolute(folder.path, library_root)
            if not folder_abs_path.exists():
                repo.delete_folder_by_path(folder_abs_path)

        repo.commit()

    return stats

