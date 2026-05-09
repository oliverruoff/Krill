"""Page-serving routes: root, setup, favicon, gateway."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from ..config import load_settings
from ..version import APP_VERSION
from .helpers import _is_setup_complete

router = APIRouter()

BASE_DIR = Path(__file__).resolve().parent.parent.parent
STATIC_DIR = BASE_DIR / "static"

_NO_STORE = "no-store, must-revalidate"


def _render_html(path: Path) -> HTMLResponse:
    """Read an HTML file and return it with no-store cache headers.

    The app version is injected as a query-string parameter on the main
    <script> tag so browsers always load the correct JS after a deploy.
    """
    text = path.read_text(encoding="utf-8")
    text = text.replace(".js\"", f".js?v={APP_VERSION}\"")
    text = text.replace(".js'", f".js?v={APP_VERSION}'")
    return HTMLResponse(
        content=text,
        headers={"Cache-Control": _NO_STORE},
    )


@router.get("/", response_class=HTMLResponse)
async def read_root() -> HTMLResponse:
    settings = await load_settings()
    page = "gateway.html" if _is_setup_complete(settings) else "setup.html"
    return _render_html(STATIC_DIR / page)


@router.get("/setup", response_class=HTMLResponse)
async def read_setup() -> HTMLResponse:
    return _render_html(STATIC_DIR / "setup.html")


@router.get("/favicon.ico", response_class=FileResponse)
async def read_favicon() -> FileResponse:
    return FileResponse(STATIC_DIR / "img" / "krill_icon.png")


@router.get("/gateway", response_class=HTMLResponse)
async def read_gateway():
    settings = await load_settings()
    if not _is_setup_complete(settings):
        return RedirectResponse(url="/setup", status_code=307)
    return _render_html(STATIC_DIR / "gateway.html")
