"""Page-serving routes: root, setup, favicon, gateway."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, RedirectResponse

from ..config import load_settings
from .helpers import _is_setup_complete

router = APIRouter()

BASE_DIR = Path(__file__).resolve().parent.parent.parent
STATIC_DIR = BASE_DIR / "static"


@router.get("/", response_class=FileResponse)
async def read_root() -> FileResponse:
    settings = await load_settings()
    page = "gateway.html" if _is_setup_complete(settings) else "setup.html"
    return FileResponse(STATIC_DIR / page)


@router.get("/setup", response_class=FileResponse)
async def read_setup() -> FileResponse:
    return FileResponse(STATIC_DIR / "setup.html")


@router.get("/favicon.ico", response_class=FileResponse)
async def read_favicon() -> FileResponse:
    return FileResponse(STATIC_DIR / "img" / "krill_icon.png")


@router.get("/gateway")
async def read_gateway():
    settings = await load_settings()
    if not _is_setup_complete(settings):
        return RedirectResponse(url="/setup", status_code=307)
    return FileResponse(STATIC_DIR / "gateway.html")
