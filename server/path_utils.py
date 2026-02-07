"""Path utilities for converting between absolute and relative paths.

All paths stored in the database are relative to the library root path.
This allows the entire library to be moved to a different location by simply
updating the library_path in config.ini.
"""

from __future__ import annotations

from pathlib import Path


def to_relative(absolute_path: Path, library_root: Path) -> str:
    """Convert an absolute path to a relative path string.
    
    Args:
        absolute_path: The absolute filesystem path
        library_root: The library root path from config
        
    Returns:
        String representation of the relative path
        
    Example:
        >>> to_relative(Path("/library/Comics/Marvel/X-Men.cbz"), Path("/library/Comics"))
        "Marvel/X-Men.cbz"
    """
    try:
        rel_path = absolute_path.relative_to(library_root)
        return str(rel_path)
    except ValueError:
        return str(absolute_path)


def to_absolute(relative_path: str, library_root: Path) -> Path:
    """Convert a relative path string to an absolute Path object.
    
    Args:
        relative_path: The relative path string from database
        library_root: The library root path from config
        
    Returns:
        Absolute Path object
        
    Example:
        >>> to_absolute("Marvel/X-Men.cbz", Path("/library/Comics"))
        Path("/library/Comics/Marvel/X-Men.cbz")
    """
    return library_root / relative_path
