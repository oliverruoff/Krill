from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import Settings, ensure_settings_file, load_settings, save_settings


BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="Krill")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.on_event("startup")
async def startup_event() -> None:
    await ensure_settings_file()


@app.get("/", response_class=FileResponse)
async def read_index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/settings", response_model=Settings)
async def get_settings() -> Settings:
    return await load_settings()


@app.post("/api/settings", response_model=Settings)
async def update_settings(settings: Settings) -> Settings:
    return await save_settings(settings)
