"""Data Access Layer for Issued.

Encapsulates database operations using SQLModel/SQLAlchemy.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Set, Tuple

from sqlmodel import Session, select, col, func

from .models import Folder, Comic, ComicMetadata
from .config import IssuedConfig
from .path_utils import to_relative, to_absolute
from .comicinfo import ComicMetadataUpdate


class Repository:
    """Data access layer that stores paths as relative to library_root in DB.
    
    All public methods accept/return absolute Path objects for convenience.
    Internally, paths are converted to relative strings before DB storage.
    """
    
    def __init__(self, session: Session, library_root: Path):
        self.session = session
        self.library_root = library_root.resolve()

    def commit(self) -> None:
        """Commit the current transaction. Callers control when to commit."""
        self.session.commit()

    def get_or_create_folder(self, path: Path) -> Folder:
        """Upsert a folder row based on its absolute path.
        
        Stores relative path in DB. Recursively creates parent folders.
        
        Args:
            path: Absolute path to the folder
            
        Returns:
            Folder object with relative path stored in DB
        """
        path = path.resolve()
        rel_path_str = to_relative(path, self.library_root)
        
        # Try finding existing by relative path
        statement = select(Folder).where(Folder.path == rel_path_str)
        folder = self.session.exec(statement).first()
        if folder:
            return folder

        # Determine parent
        parent_id = None
        if path != self.library_root:
            parent_path = path.parent
            
            # Stop recursion if we hit filesystem root or library root
            if parent_path != path and parent_path.is_relative_to(self.library_root):
                # Recursively get/create parent
                parent_folder = self.get_or_create_folder(parent_path)
                parent_id = parent_folder.id

        # Create new folder with relative path
        folder = Folder(
            name=path.name or str(path),
            path=rel_path_str,
            parent_id=parent_id
        )
        self.session.add(folder)
        self.session.flush()
        self.session.refresh(folder)
        return folder

    def upsert_comic(
        self,
        *,
        folder_id: int,
        path: Path,
        filename: str,
        fmt: str,
        file_size: int,
        page_count: int,
        file_modified_at: datetime,
        thumbnail_generated: bool = False,
    ) -> Comic:
        """Insert or update a comic.
        
        Args:
            path: Absolute path to the comic file
            
        Stores relative path in DB.
        """
        rel_path_str = to_relative(path, self.library_root)
        statement = select(Comic).where(Comic.path == rel_path_str)
        comic = self.session.exec(statement).first()

        now = datetime.now(timezone.utc)

        if comic:
            # Update
            comic.folder_id = folder_id
            comic.filename = filename
            comic.format = fmt
            comic.file_size = file_size
            comic.page_count = page_count
            comic.file_modified_at = file_modified_at
            comic.last_scanned_at = now
            comic.thumbnail_generated = thumbnail_generated
        else:
            # Insert with relative path
            comic = Comic(
                folder_id=folder_id,
                filename=filename,
                path=rel_path_str,
                format=fmt,
                file_size=file_size,
                page_count=page_count,
                file_modified_at=file_modified_at,
                last_scanned_at=now,
                thumbnail_generated=thumbnail_generated,
            )
            self.session.add(comic)
            self.session.flush()
            
            metadata = ComicMetadata(comic_id=comic.id)
            self.session.add(metadata)

        self.session.add(comic)
        self.session.flush()
        self.session.refresh(comic)
        return comic

    def get_comic_by_path(self, path: Path) -> Optional[Comic]:
        """Get comic by absolute path (converts to relative for DB query).
        
        Eagerly loads metadata_rel for checking if ComicInfo needs to be read.
        """
        from sqlmodel import select
        from sqlalchemy.orm import selectinload
        
        rel_path_str = to_relative(path, self.library_root)
        statement = (
            select(Comic)
            .where(Comic.path == rel_path_str)
            .options(selectinload(Comic.metadata_rel))
        )
        return self.session.exec(statement).first()

    def get_comic_by_id(self, comic_id: int) -> Optional[Comic]:
        return self.session.get(Comic, comic_id)

    def get_comic_by_uuid(self, comic_uuid: str) -> Optional[Comic]:
        return self.session.exec(select(Comic).where(Comic.uuid == comic_uuid)).first()

    def delete_comic_by_path(self, path: Path) -> List[str]:
        """Delete comic by absolute path and return deleted comic UUIDs."""
        rel_path_str = to_relative(path, self.library_root)
        statement = select(Comic).where(Comic.path == rel_path_str)
        comics = self.session.exec(statement).all()
        uuids = [c.uuid for c in comics]

        for comic in comics:
            self.session.delete(comic)

        self.session.flush()
        return uuids

    def delete_comics_under_path(self, base_path: Path) -> List[str]:
        """Delete all comics under absolute base_path. Returns deleted comic UUIDs."""
        rel_base_str = to_relative(base_path, self.library_root).rstrip("/")
        statement = select(Comic).where(col(Comic.path).like(f"{rel_base_str}/%"))
        comics = self.session.exec(statement).all()
        uuids = [c.uuid for c in comics]

        for comic in comics:
            self.session.delete(comic)

        self.session.flush()
        return uuids

    def delete_folder_by_path(self, path: Path) -> None:
        """Delete folder and all children by absolute path."""
        rel_path_str = to_relative(path, self.library_root).rstrip("/")
        
        # Delete child folders
        statement_folders = select(Folder).where(col(Folder.path).like(f"{rel_path_str}/%"))
        folders = self.session.exec(statement_folders).all()
        for f in folders:
            self.session.delete(f)
            
        # Delete exact folder
        exact_folder = self.session.exec(select(Folder).where(Folder.path == rel_path_str)).first()
        if exact_folder:
            self.session.delete(exact_folder)
            
        self.session.flush()

    def update_folder_path(self, old_path: Path, new_path: Path) -> bool:
        """Move a folder: update its path, its parent, and all children paths.
        
        Args:
            old_path: Old absolute path
            new_path: New absolute path
            
        Returns:
            True if folder was found and updated, False otherwise.
        """
        old_rel_str = to_relative(old_path, self.library_root).rstrip("/")
        new_rel_str = to_relative(new_path, self.library_root).rstrip("/")

        # 1. Update the folder itself
        folder = self.session.exec(select(Folder).where(Folder.path == old_rel_str)).first()
        if not folder:
            return False

        folder.path = new_rel_str
        folder.name = new_path.name
        
        # Update parent
        new_parent_path = new_path.parent
        new_parent_rel = to_relative(new_parent_path, self.library_root)
        parent = self.session.exec(select(Folder).where(Folder.path == new_parent_rel)).first()
        folder.parent_id = parent.id if parent else None
        
        self.session.add(folder)
        self.session.flush()
            
        # 2. Update children
        # Fetch all children
        statement = select(Folder).where(col(Folder.path).like(f"{old_rel_str}/%"))
        children = self.session.exec(statement).all()
        
        for child in children:
            # replace prefix
            child.path = child.path.replace(old_rel_str, new_rel_str, 1)
            self.session.add(child)
            
        self.session.flush()
        return True

    def update_comic_paths(self, old_base: Path, new_base: Path) -> None:
        """Update paths of comics when a parent folder moves.
        
        Args:
            old_base: Old absolute base path
            new_base: New absolute base path
        """
        old_rel_str = to_relative(old_base, self.library_root).rstrip("/")
        new_rel_str = to_relative(new_base, self.library_root).rstrip("/")
        
        statement = select(Comic).where(col(Comic.path).like(f"{old_rel_str}/%"))
        comics = self.session.exec(statement).all()
        
        for comic in comics:
            comic.path = comic.path.replace(old_rel_str, new_rel_str, 1)
            self.session.add(comic)
            
        self.session.flush()

    def set_thumbnail_generated(self, comic_id: int, generated: bool = True) -> None:
        comic = self.session.get(Comic, comic_id)
        if comic:
            comic.thumbnail_generated = generated
            self.session.add(comic)
            self.session.flush()

    def folder_has_subfolders(self, folder_id: int) -> bool:
        """Return True if this folder has any child folders (i.e. is not a leaf)."""
        statement = select(func.count()).select_from(Folder).where(Folder.parent_id == folder_id)
        count = self.session.exec(statement).one()
        return count > 0

    def update_comic_metadata(self, comic_id: int, payload: ComicMetadataUpdate) -> None:
        """Update metadata row for a comic. Only non-None fields in payload are set."""
        statement = select(ComicMetadata).where(ComicMetadata.comic_id == comic_id)
        meta = self.session.exec(statement).first()
        if not meta:
            meta = ComicMetadata(comic_id=comic_id)
            self.session.add(meta)
            self.session.flush()
        for key, value in payload.model_dump(exclude_none=True).items():
            setattr(meta, key, value)
        self.session.add(meta)
        self.session.flush()

    # --- Read Methods (used by thumbnails/main) ---

    def get_all_comics(self) -> List[Comic]:
         return self.session.exec(select(Comic)).all()
         
    def get_missing_thumbnails_comics(self) -> List[Comic]:
        return self.session.exec(select(Comic).where(Comic.thumbnail_generated == False)).all()

    def get_valid_thumbnail_uuids(self) -> Set[str]:
        """Return set of comic UUIDs (for orphan thumbnail cleanup)."""
        uuids = self.session.exec(select(Comic.uuid)).all()
        return set(uuids)
