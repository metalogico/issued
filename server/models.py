"""SQLModel database models for Issued."""

import uuid
from datetime import datetime, timezone
from typing import Optional, List
from sqlmodel import Field, SQLModel, Relationship

class FolderBase(SQLModel):
    name: str
    path: str = Field(unique=True, index=True)
    parent_id: Optional[int] = Field(default=None, foreign_key="folders.id")

class Folder(FolderBase, table=True):
    __tablename__ = "folders"
    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    
    # Relationships
    parent: Optional["Folder"] = Relationship(
        back_populates="children", 
        sa_relationship_kwargs={"remote_side": "Folder.id"}
    )
    children: List["Folder"] = Relationship(back_populates="parent")
    comics: List["Comic"] = Relationship(back_populates="folder")


class ComicBase(SQLModel):
    filename: str
    path: str = Field(unique=True, index=True)
    format: str
    file_size: int
    page_count: int = 0
    file_modified_at: datetime
    last_scanned_at: Optional[datetime] = None
    thumbnail_generated: bool = False
    folder_id: Optional[int] = Field(default=None, foreign_key="folders.id")

class Comic(ComicBase, table=True):
    __tablename__ = "comics"
    id: Optional[int] = Field(default=None, primary_key=True)
    uuid: str = Field(unique=True, index=True, default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    
    # Relationships
    folder: Optional[Folder] = Relationship(back_populates="comics")
    metadata_rel: Optional["ComicMetadata"] = Relationship(
        back_populates="comic",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )


class ComicMetadataBase(SQLModel):
    title: Optional[str] = None
    series: Optional[str] = None  # Set from folder name when leaf, never from ComicInfo <Series>
    issue_number: Optional[int] = None
    publisher: Optional[str] = None
    year: Optional[int] = None
    month: Optional[int] = None
    writer: Optional[str] = None
    penciller: Optional[str] = None
    artist: Optional[str] = None
    summary: Optional[str] = None
    notes: Optional[str] = None
    web: Optional[str] = None
    language_iso: Optional[str] = None
    genre: Optional[str] = None
    score: Optional[int] = None
    # Reading progress (continue reading)
    is_completed: bool = False
    current_page: Optional[int] = None  # 1-based page last viewed
    last_read_at: Optional[datetime] = None

class ComicMetadata(ComicMetadataBase, table=True):
    __tablename__ = "metadata"  # Override default table name to match legacy schema
    
    id: Optional[int] = Field(default=None, primary_key=True)
    comic_id: int = Field(foreign_key="comics.id", unique=True)
    
    # Relationships
    comic: Optional[Comic] = Relationship(back_populates="metadata_rel")
