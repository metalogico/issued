"""Issued CLI entry point."""

from __future__ import annotations

import configparser
import logging
from pathlib import Path
from typing import Optional

import typer
from sqlmodel import Session, select

from server.config import DEFAULT_CONFIG_PATH, IssuedConfig, load_config
from server.database import get_engine, init_db, reset_database
from server.migrations import get_status, run_migrations, stamp_if_needed
from server.monitor import start_file_monitoring
from server.opds import run_server
from server.repository import Repository
from server.scanner import scan_library
from server.thumbnails import cleanup_orphaned_thumbnails, generate_thumbnails
from server.models import Folder
from server.logging_config import setup_logging


__version__ = "0.1.0"

app = typer.Typer(add_completion=False, help="Issued comic library CLI")
logger = logging.getLogger("issued")

STARTUP_BANNER = r"""
 __     ______     ______     __  __     ______     _____    
/\ \   /\  ___\   /\  ___\   /\ \/\ \   /\  ___\   /\  __-.  
\ \ \  \ \___  \  \ \___  \  \ \ \_\ \  \ \  __\   \ \ \/\ \ 
 \ \_\  \/\_____\  \/\_____\  \ \_____\  \ \_____\  \ \____- 
  \/_/   \/_____/   \/_____/   \/_____/   \/_____/   \/____/ 
"""


def _ensure_config() -> IssuedConfig:
    try:
        return load_config()
    except FileNotFoundError:
        typer.echo("[ERROR] config.ini not found. Run: issued init --library /path/to/comics")
        raise typer.Exit(code=1)


def _write_config(config_path: Path, library_path: Path, library_name: str) -> None:
    parser = configparser.ConfigParser()

    parser["library"] = {
        "path": str(library_path.expanduser()),
        "name": library_name,
    }
    parser["server"] = {
        "host": "0.0.0.0",
        "port": "8181",
    }
    parser["thumbnails"] = {
        "width": "300",
        "height": "450",
        "quality": "85",
        "format": "jpeg",
    }
    parser["scanner"] = {
        "supported_formats": "cbz,cbr",
        "ignore_patterns": ".DS_Store,Thumbs.db,@eaDir",
    }
    parser["monitoring"] = {
        "enabled": "true",
        "debounce_seconds": "2",
    }
    parser["reader"] = {
        "user": "",
        "password": "",
    }

    config_path.parent.mkdir(parents=True, exist_ok=True)
    with config_path.open("w") as handle:
        parser.write(handle)


@app.command()
def init(
    library: Path = typer.Option(..., "--library", help="Path to your comics folder"),
    name: str = typer.Option("My Comic Library", "--name", help="Library name"),
) -> None:
    """Initialize config.ini with default settings."""
    config_path = DEFAULT_CONFIG_PATH
    _write_config(config_path, library, name)
    typer.echo(f"[OK] Config created at {config_path}")


@app.command()
def scan(
    force: bool = typer.Option(False, "--force", help="Force full rescan"),
    path: Optional[Path] = typer.Option(None, "--path", help="Scan a subfolder"),
) -> None:
    """Scan library and update database."""
    setup_logging()
    
    config = _ensure_config()
    stats = scan_library(config, path=path, force=force)

    typer.echo(
        "✓ Scan completed: "
        f"{stats['added']} comics added, "
        f"{stats['updated']} updated, "
        f"{stats['deleted']} deleted, "
        f"{stats['skipped']} skipped."
    )


@app.command()
def serve(
    host: Optional[str] = typer.Option(None, "--host", help="Server host"),
    port: Optional[int] = typer.Option(None, "--port", help="Server port"),
    no_watch: bool = typer.Option(False, "--no-watch", help="Disable file monitoring"),
) -> None:
    """Start OPDS server with optional file monitoring."""
    setup_logging()
    
    typer.echo(typer.style(STARTUP_BANNER, fg=typer.colors.MAGENTA, bold=True))
    config = _ensure_config()
    init_db()

    # Migrations: stamp legacy DBs, then upgrade to head.
    stamp_if_needed()
    current, head = get_status()
    if current != head:
        logger.info(f"Migrating database {current} -> {head} ...")
        run_migrations(backup=True)
        logger.info("Migration complete.")
    else:
        logger.info(f"Database at {head} (up to date).")

    # Initial scan on startup (populates DB if empty or picks up changes)
    logger.info("Running initial library scan...")
    stats = scan_library(config)
    logger.info(
        f"Scan complete: {stats['added']} added, {stats['updated']} updated, "
        f"{stats['deleted']} deleted, {stats['skipped']} skipped."
    )

    observer = None
    if not no_watch and config.monitoring.enabled:
        observer = start_file_monitoring(config)
    elif no_watch:
        logger.info("File monitoring disabled")

    try:
        run_server(config, host=host, port=port, monitoring_enabled=observer is not None)
    except KeyboardInterrupt:
        pass
    finally:
        if observer:
            observer.stop()
            observer.join()


@app.command()
def thumbnails(
    regenerate: bool = typer.Option(False, "--regenerate", help="Regenerate all thumbnails"),
) -> None:
    """Generate missing (or all) thumbnails."""
    setup_logging()
    
    config = _ensure_config()
    generate_thumbnails(config, regenerate=regenerate)


@app.command()
def cleanup() -> None:
    """Remove orphaned thumbnails."""
    config = _ensure_config()
    deleted = cleanup_orphaned_thumbnails(config)
    typer.echo(f"[INFO] Removed {deleted} orphaned thumbnails")


@app.command()
def stats() -> None:
    """Show library statistics."""
    config = _ensure_config()

    with Session(get_engine()) as session:
        repo = Repository(session, config.library_path)
        comics = repo.get_all_comics()
        folder_count = session.exec(select(Folder)).all()

    total_size = sum(comic.file_size for comic in comics)
    size_gb = total_size / (1024 ** 3)
    total_comics = len(comics)
    total_folders = len(folder_count)
    thumbs_generated = len([c for c in comics if c.thumbnail_generated])
    percent = (thumbs_generated / total_comics * 100) if total_comics else 0

    typer.echo("Library Statistics:")
    typer.echo(f"  Total comics: {total_comics}")
    typer.echo(f"  Total folders: {total_folders}")
    typer.echo(f"  Total size: {size_gb:.1f} GB")
    typer.echo(
        f"  Thumbnails generated: {thumbs_generated} / {total_comics} "
        f"({percent:.0f}%)"
    )


@app.command()
def migrate(
    check: bool = typer.Option(False, "--check", help="Print status and exit (1 if not at head)"),
) -> None:
    """Run pending database migrations (or check status with --check)."""
    _ensure_config()                    # config must exist before we touch the DB
    init_db()                           # ensure tables exist for a brand-new DB

    current, head = get_status()

    if check:
        if current == head:
            typer.echo(f"[OK] Database at {head} (head).")
            raise typer.Exit(code=0)
        else:
            typer.echo(f"[WARN] Database behind — current: {current}, head: {head}")
            raise typer.Exit(code=1)

    # Normal (non-check) path
    if current == head:
        logger.info(f"Database already at {head} (head). Nothing to do.")
        raise typer.Exit(code=0)

    logger.info(f"Migrating database {current} -> {head} ...")
    run_migrations(backup=True)
    logger.info("Migration complete.")


@app.command()
def reset(
    confirm: bool = typer.Option(False, "--confirm", help="Confirm destructive reset"),
) -> None:
    """Reset database and regenerate thumbnails."""
    if not confirm:
        typer.echo("[ERROR] This will delete your database and thumbnails. Use --confirm.")
        raise typer.Exit(code=1)

    config = _ensure_config()

    reset_database()
    thumbnails_dir = config.thumbnails_dir
    if thumbnails_dir.exists():
        for file_path in thumbnails_dir.glob("*.jpg"):
            file_path.unlink()

    typer.echo("[INFO] Database and thumbnails reset. Rescanning library...")
    scan_library(config, force=True)


if __name__ == "__main__":
    app()
