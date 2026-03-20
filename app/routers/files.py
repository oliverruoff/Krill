"""File-serving routes: TTS audio and shared files."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ..config import DATA_DIR
from ..shared_files import get_shared_file_entry

router = APIRouter()


@router.get("/api/tts/audio/{filename}")
async def serve_tts_audio(filename: str):
    if not re.fullmatch(r"[a-f0-9\-]+\.mp3", filename):
        raise HTTPException(status_code=400, detail="Invalid TTS audio filename.")
    audio_path = DATA_DIR / "tts_audio" / filename
    resolved = audio_path.resolve()
    tts_dir = (DATA_DIR / "tts_audio").resolve()
    if not str(resolved).startswith(str(tts_dir)):
        raise HTTPException(status_code=400, detail="Invalid TTS audio path.")
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="Audio file not found or expired.")
    return FileResponse(resolved, media_type="audio/mpeg", filename=filename)


@router.get("/api/files/shared/{token}")
async def serve_shared_file(token: str):
    entry = await get_shared_file_entry(token)
    if entry is None:
        raise HTTPException(status_code=404, detail="Shared file link is invalid or expired.")

    file_path = Path(str(entry.get("path", ""))).expanduser().resolve()
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Shared file is no longer available.")

    media_type = str(entry.get("media_type", "") or "application/octet-stream")
    filename = str(entry.get("filename", "") or file_path.name)
    return FileResponse(file_path, media_type=media_type, filename=filename)
