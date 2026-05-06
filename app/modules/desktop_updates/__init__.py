"""
Desktop Updates Module
─────────────────────
Serves update endpoints for the Top Chef Desktop POS application.
Completely isolated from web routes.
"""

from fastapi import FastAPI
from .router import router as desktop_updates_router


def register_desktop_updates(app: FastAPI) -> None:
    """Register desktop update endpoints under /api/desktop prefix."""
    app.include_router(
        desktop_updates_router,
        prefix="/desktop-updates",
        tags=["Desktop Updates"],
    )
