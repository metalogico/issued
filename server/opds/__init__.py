"""FastAPI OPDS server for Issued.

Exposes:
- GET /opds/                  (root navigation)
- GET /opds/folder/{folder_id}
- GET /opds/recent
- GET /opds/search
- GET /opds/comic/{comic_uuid}/file
- GET /opds/comic/{comic_uuid}/thumbnail
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from ..logging_config import get_logger  # noqa: F401 – keep for patching compat
from ..config import get_config  # noqa: F401 – re-exported for monkeypatching in tests
from .middleware import (
    ReaderAuthMiddleware,
    RequestLoggingMiddleware,
    _ReaderAccessFilter,
    _UvicornStartupFilter,
)
from .routes import router as _opds_router
from reader.routes import router as reader_router, STATIC_DIR

logger = get_logger(__name__)


def _get_lan_ip() -> Optional[str]:
    """Return this machine's LAN IP (for OPDS URL when binding to 0.0.0.0)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return None


@asynccontextmanager
async def _lifespan(app: FastAPI):
    async def _print_startup_messages():
        await asyncio.sleep(0.1)
        logger.info("Started server process [" + str(os.getpid()) + "]")
        logger.info("Application startup complete. (Press CTRL+C to quit)")
        opds_url = getattr(app.state, "opds_url_public", None)
        if opds_url:
            logger.info("OPDS server available at: " + opds_url)
        reader_url = getattr(app.state, "reader_url", None)
        if reader_url:
            logger.info("Web reader: " + reader_url)
        if getattr(app.state, "monitoring_enabled", False):
            logger.info("File monitoring enabled")

    asyncio.create_task(_print_startup_messages())
    yield


app = FastAPI(title="Issued OPDS", lifespan=_lifespan)
app.add_middleware(ReaderAuthMiddleware)
app.add_middleware(RequestLoggingMiddleware)

app.include_router(_opds_router)
app.include_router(reader_router, prefix="/reader")
app.mount("/reader/static", StaticFiles(directory=str(STATIC_DIR)), name="reader_static")


def run_server(
    config,
    host: Optional[str],
    port: Optional[int],
    monitoring_enabled: bool = False,
) -> None:
    """Run the FastAPI app with Uvicorn."""
    import uvicorn

    effective_host = host or config.server_host
    effective_port = port or config.server_port

    app.state.reader_url = f"http://localhost:{effective_port}/reader"
    app.state.monitoring_enabled = monitoring_enabled

    if effective_host == "0.0.0.0":
        lan_ip = _get_lan_ip()
        opds_host = lan_ip if lan_ip else "0.0.0.0"
    else:
        opds_host = effective_host
    app.state.opds_url_public = f"http://{opds_host}:{effective_port}/opds/"

    startup_filter = _UvicornStartupFilter()
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "uvicorn.lifespan"):
        logging.getLogger(name).addFilter(startup_filter)
    logging.getLogger().addFilter(startup_filter)
    logging.getLogger("uvicorn.access").addFilter(_ReaderAccessFilter())

    uvicorn.run(
        app,
        host=effective_host,
        port=effective_port,
        log_level="info",
        log_config=None,
    )


__all__ = ["app", "run_server", "get_config"]
