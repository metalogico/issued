"""Library management API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from server.config import get_config
from server.scanner import scan_library

router = APIRouter(tags=["reader"])


@router.post("/api/library/scan")
def api_library_scan():
    """Trigger a manual library scan and return scan stats."""
    try:
        stats = scan_library(get_config())
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Scan failed: {exc}") from exc
    return {"ok": True, "stats": stats}
