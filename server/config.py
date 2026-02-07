"""Config management for Issued.

Reads `config.ini` from the project root (beside the executable / main.py).
When running as PyInstaller onefile, PROJECT_ROOT is the directory containing the executable.
"""

from __future__ import annotations

import configparser
import dataclasses
import os
import pathlib
import sys
from typing import Optional

from .logging_config import get_logger

logger = get_logger(__name__)

def _get_project_root() -> pathlib.Path:
    if getattr(sys, "frozen", False):
        return pathlib.Path(sys.executable).resolve().parent
    return pathlib.Path(__file__).resolve().parents[1]


PROJECT_ROOT = _get_project_root()

# DATA_DIR holds all persistent state (config.ini, library.db, thumbnails/).
# Set via env var for Docker; defaults to PROJECT_ROOT for standalone use.
DATA_DIR = pathlib.Path(os.environ.get("DATA_DIR", str(PROJECT_ROOT)))
DEFAULT_CONFIG_PATH = DATA_DIR / "config.ini"


@dataclasses.dataclass
class LibraryConfig:
    path: pathlib.Path
    name: str


@dataclasses.dataclass
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 8080


@dataclasses.dataclass
class ThumbnailConfig:
    width: int = 300
    height: int = 450
    quality: int = 85
    format: str = "jpeg"


@dataclasses.dataclass
class ScannerConfig:
    supported_formats: tuple[str, ...] = ("cbz", "cbr")
    ignore_patterns: tuple[str, ...] = (".DS_Store", "Thumbs.db", "@eaDir")


@dataclasses.dataclass
class MonitoringConfig:
    enabled: bool = True
    debounce_seconds: int = 2


@dataclasses.dataclass
class ReaderAuthConfig:
    """Credentials for web reader access. If both set, login is required."""

    user: str = ""
    password: str = ""

    @property
    def enabled(self) -> bool:
        return bool(self.user.strip() and self.password)


@dataclasses.dataclass
class IssuedConfig:
    library: LibraryConfig
    server: ServerConfig
    thumbnails: ThumbnailConfig
    scanner: ScannerConfig
    monitoring: MonitoringConfig
    reader_auth: ReaderAuthConfig

    @property
    def library_path(self) -> pathlib.Path:
        return self.library.path

    @property
    def server_host(self) -> str:
        return self.server.host

    @property
    def server_port(self) -> int:
        return self.server.port

    @property
    def database_path(self) -> pathlib.Path:
        return DATA_DIR / "library.db"

    @property
    def thumbnails_dir(self) -> pathlib.Path:
        return DATA_DIR / "thumbnails"


def _parse_bool(value: str, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_config(config_path: Optional[pathlib.Path] = None) -> IssuedConfig:
    """Load configuration from config.ini.

    Defaults to `config.ini` in the project root.
    """
    path = config_path or DEFAULT_CONFIG_PATH
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    parser = configparser.ConfigParser()
    parser.read(path)

    lib_path = pathlib.Path(
        parser.get("library", "path", fallback="/path/to/comics")
    ).expanduser()
    lib_name = parser.get("library", "name", fallback="My Comic Library")

    server = ServerConfig(
        host=parser.get("server", "host", fallback="0.0.0.0"),
        port=parser.getint("server", "port", fallback=8080),
    )

    thumbs = ThumbnailConfig(
        width=parser.getint("thumbnails", "width", fallback=300),
        height=parser.getint("thumbnails", "height", fallback=450),
        quality=parser.getint("thumbnails", "quality", fallback=85),
        format=parser.get("thumbnails", "format", fallback="jpeg"),
    )

    scanner = ScannerConfig(
        supported_formats=tuple(
            f.strip()
            for f in parser.get(
                "scanner", "supported_formats", fallback="cbz,cbr"
            ).split(",")
            if f.strip()
        ),
        ignore_patterns=tuple(
            p.strip()
            for p in parser.get(
                "scanner",
                "ignore_patterns",
                fallback=".DS_Store,Thumbs.db,@eaDir",
            ).split(",")
            if p.strip()
        ),
    )

    monitoring = MonitoringConfig(
        enabled=_parse_bool(
            parser.get("monitoring", "enabled", fallback="true"), True
        ),
        debounce_seconds=parser.getint(
            "monitoring", "debounce_seconds", fallback=2
        ),
    )

    if parser.has_section("reader"):
        reader_auth = ReaderAuthConfig(
            user=parser.get("reader", "user", fallback="").strip(),
            password=parser.get("reader", "password", fallback="").strip(),
        )
    else:
        reader_auth = ReaderAuthConfig()

    return IssuedConfig(
        library=LibraryConfig(path=lib_path, name=lib_name),
        server=server,
        thumbnails=thumbs,
        scanner=scanner,
        monitoring=monitoring,
        reader_auth=reader_auth,
    )


_cached_config: Optional[IssuedConfig] = None


def get_config() -> IssuedConfig:
    """Return the cached config singleton. Loads from disk on first call."""
    global _cached_config
    if _cached_config is None:
        _cached_config = load_config()
    return _cached_config


def reset_config_cache() -> None:
    """Clear the cached config (useful for tests)."""
    global _cached_config
    _cached_config = None


def ensure_config(
    library_path: pathlib.Path, config_path: Optional[pathlib.Path] = None
) -> pathlib.Path:
    """Create a default config.ini (and folders) if missing.

    - Writes `config.ini` based on `config.ini.example` but with the given library path.
    - Ensures `thumbnails/` directory exists.
    - Does NOT create the SQLite database yet (that will be done by database module).
    """
    path = config_path or DEFAULT_CONFIG_PATH

    if getattr(sys, "frozen", False):
        example_path = pathlib.Path(sys._MEIPASS) / "config.ini.example"
    else:
        example_path = PROJECT_ROOT / "config.ini.example"
    if not example_path.exists():
        logger.error(f"config.ini.example not found at {example_path}")
        raise FileNotFoundError(f"config.ini.example not found at {example_path}")

    content = example_path.read_text(encoding="utf-8")

    # Replace library path line in the example content
    lines = []
    in_library_section = False
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_library_section = stripped.lower() == "[library]"
            lines.append(line)
            continue

        if in_library_section and stripped.startswith("path "):
            lines.append(f"path = {library_path}")
        else:
            lines.append(line)

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    thumbnails_dir = DATA_DIR / "thumbnails"
    thumbnails_dir.mkdir(parents=True, exist_ok=True)

    return path

