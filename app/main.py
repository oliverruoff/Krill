import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import Settings, ensure_settings_file, load_settings, save_settings
from .providers import get_provider, get_provider_model_ids, get_provider_options, is_supported_provider


BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="Krill")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class ModelOption(BaseModel):
    id: str
    label: str


class ProviderOption(BaseModel):
    id: str
    label: str
    models: list[ModelOption]


class VerifyProviderRequest(BaseModel):
    provider_id: str
    model: str
    api_key: str


class VerifyProviderResponse(BaseModel):
    ok: bool
    detail: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=5000)


@app.on_event("startup")
async def startup_event() -> None:
    await ensure_settings_file()


@app.get("/", response_class=FileResponse)
async def read_root() -> FileResponse:
    settings = await load_settings()
    page = "gateway.html" if _is_setup_complete(settings) else "setup.html"
    return FileResponse(STATIC_DIR / page)


@app.get("/setup", response_class=FileResponse)
async def read_setup() -> FileResponse:
    return FileResponse(STATIC_DIR / "setup.html")


@app.get("/krill_banner.png", response_class=FileResponse)
async def read_banner() -> FileResponse:
    return FileResponse(BASE_DIR / "krill_banner.png")


@app.get("/gateway")
async def read_gateway():
    settings = await load_settings()

    if not _is_setup_complete(settings):
        return RedirectResponse(url="/setup", status_code=307)

    return FileResponse(STATIC_DIR / "gateway.html")


@app.get("/api/settings", response_model=Settings)
async def get_settings() -> Settings:
    return await load_settings()


@app.get("/api/providers", response_model=list[ProviderOption])
async def get_providers() -> list[dict[str, object]]:
    return get_provider_options()


@app.post("/api/settings", response_model=Settings)
async def update_settings(settings: Settings) -> Settings:
    _validate_settings_payload(settings)
    return await save_settings(settings)


@app.post("/api/braindump/import", response_model=Settings)
async def import_braindump(settings: Settings) -> Settings:
    _validate_settings_payload(settings)
    return await save_settings(settings)


@app.post("/api/providers/verify", response_model=VerifyProviderResponse)
async def verify_provider(payload: VerifyProviderRequest) -> VerifyProviderResponse:
    if not is_supported_provider(payload.provider_id):
        raise HTTPException(status_code=422, detail="Unsupported LLM provider.")

    model_ids = get_provider_model_ids(payload.provider_id)
    if payload.model not in model_ids:
        raise HTTPException(status_code=422, detail="Unsupported model for provider.")

    provider = get_provider(payload.provider_id)
    if provider is None:
        raise HTTPException(status_code=422, detail="Provider not found.")

    ok, detail = await provider.verify(payload.model, payload.api_key)
    if not ok:
        raise HTTPException(status_code=422, detail=detail)

    return VerifyProviderResponse(ok=True, detail=detail)


@app.post("/api/reset", response_model=Settings)
async def reset_settings() -> Settings:
    defaults = Settings()
    return await save_settings(defaults)


@app.post("/api/chat/stream")
async def chat_stream(payload: ChatRequest) -> StreamingResponse:
    settings = await load_settings()
    if not _is_setup_complete(settings):
        raise HTTPException(status_code=422, detail="Setup is not complete.")

    active_provider_id = settings.active_provider_id
    provider_config = settings.provider_configs.get(active_provider_id)

    if provider_config is None:
        raise HTTPException(status_code=422, detail="Active provider is not configured.")

    provider = get_provider(active_provider_id)
    if provider is None:
        raise HTTPException(status_code=422, detail="Active provider is unavailable.")

    async def event_stream():
        try:
            text = await provider.generate(
                prompt=payload.message,
                system_prompt=settings.system_prompt,
                model=provider_config.model,
                api_key=provider_config.api_key,
            )

            for chunk in _chunk_text(text):
                yield _sse("token", {"text": chunk})
                await asyncio.sleep(0.01)

            yield _sse("done", {"ok": True})
        except Exception as exc:
            yield _sse("error", {"detail": str(exc)})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


def _validate_provider_configs(settings: Settings) -> None:
    if settings.active_provider_id and settings.active_provider_id not in settings.provider_configs:
        raise HTTPException(status_code=422, detail="Active provider must exist in provider configs.")

    for provider_id, provider_config in settings.provider_configs.items():
        if not is_supported_provider(provider_id):
            raise HTTPException(status_code=422, detail=f"Unsupported LLM provider: {provider_id}")

        model_ids = get_provider_model_ids(provider_id)
        if provider_config.model and provider_config.model not in model_ids:
            raise HTTPException(
                status_code=422,
                detail=f"Unsupported model '{provider_config.model}' for provider '{provider_id}'.",
            )


def _validate_settings_payload(settings: Settings) -> None:
    _validate_provider_configs(settings)

    if settings.setup_completed and not _can_complete_setup(settings):
        raise HTTPException(
            status_code=422,
            detail="Setup cannot be marked complete without active provider, model, and API key.",
        )


def _can_complete_setup(settings: Settings) -> bool:
    if not settings.active_provider_id:
        return False

    active_config = settings.provider_configs.get(settings.active_provider_id)
    if active_config is None:
        return False

    if not active_config.api_key.strip():
        return False

    if not active_config.model:
        return False

    return active_config.model in get_provider_model_ids(settings.active_provider_id)


def _is_setup_complete(settings: Settings) -> bool:
    if not settings.setup_completed:
        return False

    return _can_complete_setup(settings)


def _sse(event_name: str, payload: dict[str, object]) -> str:
    return f"event: {event_name}\ndata: {json.dumps(payload)}\n\n"


def _chunk_text(text: str) -> list[str]:
    tokens = text.split(" ")

    if len(tokens) <= 1:
        return [text]

    return [f"{token} " for token in tokens[:-1]] + [tokens[-1]]
