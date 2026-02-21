from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import Settings, ensure_settings_file, load_settings, save_settings
from .providers import get_provider_options, is_supported_provider


BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="Krill")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class ProviderOption(BaseModel):
    id: str
    label: str


@app.on_event("startup")
async def startup_event() -> None:
    await ensure_settings_file()


@app.get("/", response_class=FileResponse)
async def read_index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/settings", response_model=Settings)
async def get_settings() -> Settings:
    return await load_settings()


@app.get("/api/providers", response_model=list[ProviderOption])
async def get_providers() -> list[dict[str, str]]:
    return get_provider_options()


@app.post("/api/settings", response_model=Settings)
async def update_settings(settings: Settings) -> Settings:
    if not is_supported_provider(settings.llm_provider):
        raise HTTPException(status_code=422, detail="Unsupported LLM provider.")

    return await save_settings(settings)
