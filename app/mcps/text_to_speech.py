"""Text to Speech MCP plugin using edge-tts for local audio generation."""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from uuid import uuid4

from app.config import DATA_DIR

from .base import McpConfigField, McpConfigFieldOption, McpToolSpec

logger = logging.getLogger(__name__)

TTS_AUDIO_DIR = (DATA_DIR / "tts_audio").resolve()
_TTS_CLEANUP_MAX_AGE_SECONDS = 24 * 60 * 60  # 24 hours

_VOICE_OPTIONS: list[McpConfigFieldOption] = [
    McpConfigFieldOption(value="en-US-JennyNeural", label="Jenny (en-US, Female)"),
    McpConfigFieldOption(value="en-US-GuyNeural", label="Guy (en-US, Male)"),
    McpConfigFieldOption(value="en-US-AriaNeural", label="Aria (en-US, Female)"),
    McpConfigFieldOption(value="en-US-DavisNeural", label="Davis (en-US, Male)"),
    McpConfigFieldOption(value="en-GB-SoniaNeural", label="Sonia (en-GB, Female)"),
    McpConfigFieldOption(value="en-GB-RyanNeural", label="Ryan (en-GB, Male)"),
    McpConfigFieldOption(value="de-DE-KatjaNeural", label="Katja (de-DE, Female)"),
    McpConfigFieldOption(value="de-DE-ConradNeural", label="Conrad (de-DE, Male)"),
    McpConfigFieldOption(value="fr-FR-DeniseNeural", label="Denise (fr-FR, Female)"),
    McpConfigFieldOption(value="fr-FR-HenriNeural", label="Henri (fr-FR, Male)"),
    McpConfigFieldOption(value="es-ES-ElviraNeural", label="Elvira (es-ES, Female)"),
    McpConfigFieldOption(value="es-ES-AlvaroNeural", label="Alvaro (es-ES, Male)"),
    McpConfigFieldOption(value="it-IT-ElsaNeural", label="Elsa (it-IT, Female)"),
    McpConfigFieldOption(value="it-IT-DiegoNeural", label="Diego (it-IT, Male)"),
    McpConfigFieldOption(value="pt-BR-FranciscaNeural", label="Francisca (pt-BR, Female)"),
    McpConfigFieldOption(value="ja-JP-NanamiNeural", label="Nanami (ja-JP, Female)"),
    McpConfigFieldOption(value="zh-CN-XiaoxiaoNeural", label="Xiaoxiao (zh-CN, Female)"),
    McpConfigFieldOption(value="ko-KR-SunHiNeural", label="SunHi (ko-KR, Female)"),
    McpConfigFieldOption(value="nl-NL-ColetteNeural", label="Colette (nl-NL, Female)"),
    McpConfigFieldOption(value="pl-PL-AgnieszkaNeural", label="Agnieszka (pl-PL, Female)"),
    McpConfigFieldOption(value="ru-RU-SvetlanaNeural", label="Svetlana (ru-RU, Female)"),
    McpConfigFieldOption(value="ar-SA-ZariyahNeural", label="Zariyah (ar-SA, Female)"),
    McpConfigFieldOption(value="hi-IN-SwaraNeural", label="Swara (hi-IN, Female)"),
    McpConfigFieldOption(value="tr-TR-EmelNeural", label="Emel (tr-TR, Female)"),
]


class TextToSpeechMCP:
    mcp_id = "text_to_speech"
    display_name = "Text to Speech"
    description = (
        "Converts text to speech audio using edge-tts neural voices. "
        "Use when the user asks for audio output, a voice response, "
        "to read something aloud, or to speak to them by voice."
    )
    config_fields = [
        McpConfigField(
            id="voice",
            label="Default Voice",
            type="select",
            required=False,
            description="Default voice for text-to-speech. Can be overridden per request.",
            options=_VOICE_OPTIONS,
        )
    ]

    def tool_specs(self) -> list[McpToolSpec]:
        return [
            McpToolSpec(
                id="generate_speech",
                label="Generate Speech Audio",
                description=(
                    "Converts the given text to speech audio. "
                    "Returns an audio URL that can be played by the user."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "minLength": 1,
                            "description": "The text to convert to speech audio.",
                        },
                        "voice": {
                            "type": "string",
                            "description": (
                                "Optional voice override (e.g. 'en-US-JennyNeural'). "
                                "If omitted, the configured default voice is used."
                            ),
                        },
                    },
                    "required": ["text"],
                },
            )
        ]

    async def verify(self, params: dict[str, str]) -> tuple[bool, str]:
        try:
            import edge_tts  # noqa: F401
        except ImportError:
            return False, "edge-tts package is not installed. Run: pip install edge-tts"

        try:
            communicate = edge_tts.Communicate("test", "en-US-JennyNeural")
            _ensure_tts_dir()
            test_path = TTS_AUDIO_DIR / "_verify_test.mp3"
            try:
                await communicate.save(str(test_path))
                if not test_path.exists() or test_path.stat().st_size == 0:
                    return False, "edge-tts generated an empty audio file during verification."
            finally:
                test_path.unlink(missing_ok=True)
        except Exception as exc:
            return False, f"edge-tts verification failed: {exc}"

        return True, "Text to Speech is working."

    async def call_tool(
        self, tool_id: str, arguments: dict[str, object], params: dict[str, str]
    ) -> dict[str, object]:
        if tool_id != "generate_speech":
            raise RuntimeError(f"Unsupported Text to Speech tool: {tool_id}")

        try:
            import edge_tts
        except ImportError:
            raise RuntimeError("edge-tts package is not installed. Run: pip install edge-tts")

        text = arguments.get("text")
        if not isinstance(text, str) or not text.strip():
            raise RuntimeError("generate_speech requires a non-empty 'text' argument.")

        text = text.strip()

        # Resolve voice: argument override > config > default
        voice_arg = arguments.get("voice")
        voice = (
            voice_arg.strip()
            if isinstance(voice_arg, str) and voice_arg.strip()
            else params.get("voice", "").strip() or "en-US-JennyNeural"
        )

        _ensure_tts_dir()
        _cleanup_old_audio_files()

        file_id = str(uuid4())
        filename = f"{file_id}.mp3"
        filepath = TTS_AUDIO_DIR / filename

        try:
            communicate = edge_tts.Communicate(text, voice)
            await communicate.save(str(filepath))
        except Exception as exc:
            filepath.unlink(missing_ok=True)
            raise RuntimeError(f"edge-tts audio generation failed: {exc}") from exc

        if not filepath.exists() or filepath.stat().st_size == 0:
            filepath.unlink(missing_ok=True)
            raise RuntimeError("edge-tts generated an empty audio file.")

        audio_url = f"/api/tts/audio/{filename}"
        file_size_kb = round(filepath.stat().st_size / 1024, 1)

        logger.info("TTS generated: %s (%.1f KB, voice=%s)", filename, file_size_kb, voice)

        return {
            "status": "ok",
            "audio_url": audio_url,
            "text": text,
            "voice": voice,
            "file_size_kb": file_size_kb,
            "audio_file": filename,
        }

    def tool_call_system_reminder(self, tool_id: str, params: dict[str, str]) -> str:
        if tool_id == "generate_speech":
            return (
                "After generating speech audio, you MUST always include the full spoken text "
                "in your response first so the user can read it. Then include the audio URL "
                "on its own line below the text. The audio URL will be automatically rendered "
                "as a playable voice message player in the UI. "
                "Never replace the text content with just the audio link. "
                "The text must always be readable even if the audio file expires later."
            )
        return ""


def _ensure_tts_dir() -> None:
    """Create the TTS audio directory if it does not exist."""
    TTS_AUDIO_DIR.mkdir(parents=True, exist_ok=True)


def _cleanup_old_audio_files() -> None:
    """Delete TTS audio files older than the configured max age."""
    if not TTS_AUDIO_DIR.exists():
        return
    now = time.time()
    try:
        for file in TTS_AUDIO_DIR.iterdir():
            if not file.is_file() or not file.suffix == ".mp3":
                continue
            if file.name.startswith("_"):
                continue
            try:
                age = now - file.stat().st_mtime
                if age > _TTS_CLEANUP_MAX_AGE_SECONDS:
                    file.unlink(missing_ok=True)
                    logger.debug("TTS cleanup: removed %s (age=%.0fs)", file.name, age)
            except OSError:
                pass
    except OSError:
        pass
