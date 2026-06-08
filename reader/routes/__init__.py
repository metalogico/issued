"""reader.routes – feature-domain route sub-package.

Assembles every sub-router into a single ``router`` and re-exports
``TEMPLATES_DIR`` / ``STATIC_DIR`` so existing callers (e.g. server/opds.py)
continue to import them from ``reader.router``.
"""

from __future__ import annotations

from fastapi import APIRouter

from ._common import TEMPLATES_DIR, STATIC_DIR  # noqa: F401 – re-exported
from .auth import router as _auth_router
from .browse import router as _browse_router
from .api_comic import router as _api_comic_router
from .api_folder import router as _api_folder_router
from .api_library import router as _api_library_router

router = APIRouter(tags=["reader"])
router.include_router(_auth_router)
router.include_router(_browse_router)
router.include_router(_api_comic_router)
router.include_router(_api_folder_router)
router.include_router(_api_library_router)

__all__ = ["router", "TEMPLATES_DIR", "STATIC_DIR"]
