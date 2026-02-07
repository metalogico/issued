"""Thumbnail generation for Issued.

Generates JPEG thumbnails from the first page of CBZ/CBR archives,
storing them under `thumbnails/{comic_uuid}.jpg`.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image
from sqlmodel import Session

from .config import IssuedConfig
from .database import get_engine
from .logging_config import get_logger
from .repository import Repository
from .utils import short_path

logger = get_logger(__name__)


def _extract_first_image_bytes(path: Path) -> bytes | None:
    from .archive import get_archive

    try:
        with get_archive(path) as archive:
            images = archive.list_images()
            images.sort()
            
            if not images:
                logger.error(f"No images found in archive {path.name}")
                return None
            
            return archive.read(images[0])
            
    except (FileNotFoundError, PermissionError) as exc:
        logger.error(f"Unable to read archive {path.name}: {exc}")
        return None
    except Exception as exc:
        logger.error(f"Unexpected error while reading archive {path.name}: {exc}")
        return None


def _save_thumbnail(
    img_bytes: bytes,
    thumb_path: Path,
    width: int,
    height: int,
    quality: int,
) -> None:
    thumb_path.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(BytesIO(img_bytes)) as im:
        im = im.convert("RGB")
        im.thumbnail((width, height))
        im.save(thumb_path, format="JPEG", quality=quality, optimize=True)


def generate_thumbnail_for_comic(
    comic_uuid: str,
    comic_path: Path,
    config: IssuedConfig,
    repo: Repository = None,
) -> bool:
    """Generate thumbnail for a single comic.

    Args:
        comic_uuid: Comic UUID for thumbnail filename
        comic_path: Absolute path to the comic file

    Returns True if successful, False otherwise.
    """
    local_session = None
    if repo is None:
        local_session = Session(get_engine())
        repo = Repository(local_session, config.library_path)

    try:
        if not comic_path.exists():
            return False

        img_bytes = _extract_first_image_bytes(comic_path)
        if not img_bytes:
            return False

        thumb_path = config.thumbnails_dir / f"{comic_uuid}.jpg"
        try:
            _save_thumbnail(
                img_bytes,
                thumb_path,
                config.thumbnails.width,
                config.thumbnails.height,
                config.thumbnails.quality,
            )
        except Exception:
            return False

        comic = repo.get_comic_by_uuid(comic_uuid)
        if comic and comic.id is not None:
            repo.set_thumbnail_generated(comic.id, True)
            repo.commit()
        return True
    finally:
        if local_session:
            local_session.close()


def cleanup_orphaned_thumbnails(config: IssuedConfig) -> int:
    """Remove thumbnail files that don't have corresponding comics in DB.
    
    Returns count of deleted orphaned thumbnails.
    """
    with Session(get_engine()) as session:
        repo = Repository(session, config.library_path)
        valid_uuids = {comic.uuid for comic in repo.get_all_comics()}

        thumbnails_dir = config.thumbnails_dir
        if not thumbnails_dir.exists():
            return 0

        deleted = 0
        for thumb_file in thumbnails_dir.glob("*.jpg"):
            try:
                comic_uuid = thumb_file.stem
                if comic_uuid not in valid_uuids:
                    thumb_file.unlink()
                    deleted += 1
            except OSError as exc:
                logger.error(f"Failed to process thumbnail {thumb_file}: {exc}")
        
        return deleted


def generate_thumbnails(config: IssuedConfig, regenerate: bool = False) -> None:
    """Generate missing (or all) thumbnails based on DB contents."""
    with Session(get_engine()) as session:
        repo = Repository(session, config.library_path)
        
        if regenerate:
            logger.info("Regenerating all thumbnails...")
            comics = repo.get_all_comics()
        else:
            logger.info("Generating missing thumbnails...")
            comics = repo.get_missing_thumbnails_comics()

        total = len(comics)
        logger.info(f"{total} comics to process for thumbnails")

        from .path_utils import to_absolute

        for idx, comic in enumerate(comics, start=1):
            path = to_absolute(comic.path, config.library_path)

            logger.debug(f"[{idx}/{total}] {short_path(path)}")
            if not path.exists():
                logger.warning(f"Comic file not found on disk: {path}")
                continue

            img_bytes = _extract_first_image_bytes(path)
            if not img_bytes:
                continue

            thumb_path = config.thumbnails_dir / f"{comic.uuid}.jpg"
            try:
                _save_thumbnail(
                    img_bytes,
                    thumb_path,
                    config.thumbnails.width,
                    config.thumbnails.height,
                    config.thumbnails.quality,
                )
            except Exception as exc:
                logger.error(f"Failed to save thumbnail for {short_path(path)}: {exc}")
                continue

            if comic.id is not None:
                repo.set_thumbnail_generated(comic.id, True)
                repo.commit()

        logger.info("Thumbnail generation complete.")

