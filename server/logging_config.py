"""Logging configuration for Issued.

Provides centralized logging setup with:
- File handler with rotation (10MB, 5 backups)
- Rich console handler with colored output
- Consistent formatting across all modules
"""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler
from rich.theme import Theme


_logging_initialized = False


def _get_data_dir() -> Path:
    """Return the data directory (same as config.DATA_DIR without circular import)."""
    env = os.environ.get("DATA_DIR")
    if env:
        return Path(env)
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def setup_logging(log_level: str = "INFO") -> None:
    """Initialize logging with file and console handlers.
    
    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR)
    """
    global _logging_initialized
    
    if _logging_initialized:
        return
    
    # Convert string level to logging constant
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)
    
    # Create issued.log in DATA_DIR (writable in Docker)
    data_dir = _get_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    log_file = data_dir / "issued.log"
    
    # File handler with rotation (10MB, 5 backups)
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)  # Capture everything to file
    file_formatter = logging.Formatter(
        "%(asctime)s - %(levelname)-8s - %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(file_formatter)
    
    # Console handler with Rich for colored output
    # Custom theme with violet for INFO level
    custom_theme = Theme({
        "logging.level.info": "bold magenta",
    })
    console = Console(theme=custom_theme)
    
    console_handler = RichHandler(
        console=console,
        rich_tracebacks=True,
        show_time=False,  # Rich adds its own timestamp
        show_path=False,  # Don't show full file paths in console
    )
    console_handler.setLevel(numeric_level)
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)  # Capture everything, handlers filter
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    
    # Silence noisy third-party loggers
    logging.getLogger("watchdog").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    
    # Configure alembic to use our handlers (remove its own)
    alembic_logger = logging.getLogger("alembic")
    alembic_logger.handlers = []
    alembic_logger.propagate = True
    
    _logging_initialized = True


def get_logger(name: str) -> logging.Logger:
    """Get a logger for the specified module.
    
    Args:
        name: Module name (typically __name__)
        
    Returns:
        Logger instance for the module
    """
    return logging.getLogger(name)
