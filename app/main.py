"""FastAPI application entrypoint: app setup, middleware, and lifecycle events."""

import asyncio
import logging
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .auth import is_bootstrap_required, resolve_session_from_request
from .config import ensure_settings_file
from .integrations import get_runtime_integrations
from .memory_extraction import start_memory_extraction_worker, stop_memory_extraction_worker
from .oauth_refresh import start_oauth_refresh_worker, stop_oauth_refresh_worker
from .timed_jobs import start_timed_jobs_worker, stop_timed_jobs_worker

from .routers.auth import router as auth_router
from .routers.chat import router as chat_router, shutdown_gateway
from .routers.files import router as files_router
from .routers.gemini_oauth import router as gemini_oauth_router
from .routers.google_oauth import router as google_oauth_router
from .routers.integrations import router as integrations_router
from .routers.mcps import router as mcps_router
from .routers.memory import router as memory_router
from .routers.openai_oauth import router as openai_oauth_router
from .routers.pages import router as pages_router
from .routers.providers import router as providers_router
from .routers.settings import router as settings_router, rehydrate_git_ssh_material
from .routers.timed_jobs import router as timed_jobs_router

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
_DEFAULT_LOG_LEVEL = "DEBUG"
_LOG_LEVEL_ENV = "KRILL_LOG_LEVEL"


def _resolve_log_level(raw_value: str) -> int | None:
    normalized = raw_value.strip().upper()
    if not normalized:
        return None
    level = getattr(logging, normalized, None)
    return level if isinstance(level, int) else None


def _configure_logging() -> tuple[str, int]:
    raw_level = os.getenv(_LOG_LEVEL_ENV, _DEFAULT_LOG_LEVEL)
    resolved_level = _resolve_log_level(raw_level)
    if resolved_level is None:
        raw_level = _DEFAULT_LOG_LEVEL
        resolved_level = logging.DEBUG

    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=resolved_level,
            format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        )

    logging.getLogger("app").setLevel(resolved_level)
    return raw_level.upper(), resolved_level

if os.name == "nt":
    try:
        policy = asyncio.get_event_loop_policy()
        proactor_policy = getattr(asyncio, "WindowsProactorEventLoopPolicy", None)
        if proactor_policy is not None and not isinstance(policy, proactor_policy):
            asyncio.set_event_loop_policy(proactor_policy())
    except Exception:
        pass

app = FastAPI(title="Krill")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Auth and OAuth routers (no prefix)
app.include_router(auth_router)
app.include_router(gemini_oauth_router)
app.include_router(google_oauth_router)
app.include_router(openai_oauth_router)

# Feature routers
app.include_router(pages_router)
app.include_router(files_router)
app.include_router(settings_router)
app.include_router(chat_router)
app.include_router(memory_router)
app.include_router(providers_router)
app.include_router(mcps_router)
app.include_router(integrations_router)
app.include_router(timed_jobs_router)

logger = logging.getLogger(__name__)
_CONFIGURED_LOG_LEVEL_NAME, _ = _configure_logging()


# ---------------------------------------------------------------------------
# Authentication middleware
# ---------------------------------------------------------------------------

@app.middleware("http")
async def require_authentication(request: Request, call_next):
    path = request.url.path or "/"

    if await is_bootstrap_required():
        if path == "/auth/setup" or path.startswith("/api/auth/") or path.startswith("/api/files/shared/"):
            return await call_next(request)
        if path == "/login":
            return RedirectResponse(url="/auth/setup", status_code=307)
        if path.startswith("/api/"):
            return JSONResponse(status_code=428, content={"detail": "Authentication bootstrap is required."})
        return RedirectResponse(url="/auth/setup", status_code=307)

    if path in {"/login", "/favicon.ico"} or path.startswith("/api/auth/") or path.startswith("/api/files/shared/"):
        return await call_next(request)

    session = await resolve_session_from_request(request)
    if session is None:
        if path.startswith("/api/"):
            return JSONResponse(status_code=401, content={"detail": "Not authenticated."})
        return RedirectResponse(url="/login", status_code=307)

    request.state.auth_user_id = session["user_id"]
    request.state.auth_username = session["username"]
    return await call_next(request)


# ---------------------------------------------------------------------------
# Lifecycle events
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def startup_event() -> None:
    logger.info("Application logging configured at %s via %s", _CONFIGURED_LOG_LEVEL_NAME, _LOG_LEVEL_ENV)
    await ensure_settings_file()
    await rehydrate_git_ssh_material()
    await start_memory_extraction_worker()
    await start_timed_jobs_worker()
    await start_oauth_refresh_worker()
    for integration in get_runtime_integrations():
        integration.start()


@app.on_event("shutdown")
async def shutdown_event() -> None:
    await shutdown_gateway()
    await stop_memory_extraction_worker()
    await stop_timed_jobs_worker()
    await stop_oauth_refresh_worker()
    for integration in get_runtime_integrations():
        await integration.stop()
