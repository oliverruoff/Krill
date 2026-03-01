"""YouTube Summarizer MCP plugin for transcript retrieval and summarization."""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any
from urllib.parse import parse_qs, urlparse

from app.config import load_settings
from app.providers import get_provider
from app.providers.resilience import generate_with_retries

from .base import MCPPlugin, McpConfigField, McpToolSpec

try:
    from youtube_transcript_api import YouTubeTranscriptApi
except Exception as exc:  # pragma: no cover - dependency may be missing in some environments
    YouTubeTranscriptApi = None
    _YOUTUBE_TRANSCRIPT_IMPORT_ERROR = str(exc)
else:
    _YOUTUBE_TRANSCRIPT_IMPORT_ERROR = ""


_VIDEO_ID_REGEX = re.compile(r"^[a-zA-Z0-9_-]{11}$")
_DETAIL_LEVELS = {"brief", "standard", "detailed"}


class YouTubeSummarizerMCP(MCPPlugin):
    mcp_id = "youtube_summarizer"
    display_name = "YouTube Summarizer"
    description = (
        "Fetches YouTube transcripts and returns a concise, standard, or detailed summary. "
        "Use this when the user asks what a YouTube video is about."
    )
    default_enabled = True
    config_fields: list[McpConfigField] = []

    def tool_specs(self) -> list[McpToolSpec]:
        return [
            McpToolSpec(
                id="summarize_youtube_video",
                label="Summarize YouTube Video",
                description=(
                    "Summarizes a YouTube video by extracting its transcript. "
                    "Supports brief, standard, and detailed summary depth."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "video": {
                            "type": "string",
                            "minLength": 1,
                            "description": "YouTube video URL or video ID.",
                        },
                        "detail_level": {
                            "type": "string",
                            "enum": ["brief", "standard", "detailed"],
                        },
                        "language_codes": {
                            "type": "array",
                            "items": {"type": "string", "minLength": 2, "maxLength": 10},
                            "minItems": 1,
                            "maxItems": 10,
                            "description": "Preferred transcript languages in fallback order, e.g. ['en', 'de'].",
                        },
                    },
                    "required": ["video"],
                },
            )
        ]

    async def verify(self, params: dict[str, str]) -> tuple[bool, str]:
        del params
        if YouTubeTranscriptApi is None:
            return False, (
                "youtube-transcript-api is not installed. "
                f"Import error: {_YOUTUBE_TRANSCRIPT_IMPORT_ERROR or 'unknown error'}"
            )
        return True, "YouTube Summarizer MCP is ready."

    async def call_tool(self, tool_id: str, arguments: dict[str, object], params: dict[str, str]) -> dict[str, object]:
        del params
        if tool_id != "summarize_youtube_video":
            raise RuntimeError(f"Unsupported YouTube Summarizer tool: {tool_id}")

        if YouTubeTranscriptApi is None:
            raise RuntimeError(
                "youtube-transcript-api is not installed in this runtime. "
                f"Import error: {_YOUTUBE_TRANSCRIPT_IMPORT_ERROR or 'unknown error'}"
            )

        video_input = _required_str(arguments, "video")
        detail_level = _normalize_detail_level(arguments.get("detail_level"))
        language_codes = _normalize_language_codes(arguments.get("language_codes"))

        video_id = _extract_video_id(video_input)
        if not video_id:
            raise RuntimeError("Could not extract a valid YouTube video ID from 'video'.")

        transcript_payload = await asyncio.to_thread(_fetch_transcript_payload, video_id, language_codes)
        summary_payload = await _summarize_transcript(
            transcript_payload=transcript_payload,
            detail_level=detail_level,
        )

        return {
            "ok": True,
            "video": {
                "input": video_input,
                "video_id": video_id,
                "url": f"https://www.youtube.com/watch?v={video_id}",
            },
            "detail_level": detail_level,
            "transcript": {
                "language": transcript_payload["language"],
                "language_code": transcript_payload["language_code"],
                "is_generated": transcript_payload["is_generated"],
                "snippet_count": transcript_payload["snippet_count"],
                "duration_seconds": transcript_payload["duration_seconds"],
                "character_count": transcript_payload["character_count"],
            },
            "summary": summary_payload.get("summary", ""),
            "key_points": summary_payload.get("key_points", []),
        }


def _fetch_transcript_payload(video_id: str, language_codes: list[str]) -> dict[str, object]:
    ytt_api = YouTubeTranscriptApi()

    try:
        fetched = ytt_api.fetch(video_id, languages=language_codes)
        snippets, full_text, duration_seconds = _normalize_fetched_snippets(fetched)
        language = _safe_str(getattr(fetched, "language", ""))
        language_code = _safe_str(getattr(fetched, "language_code", ""))
        is_generated = bool(getattr(fetched, "is_generated", False))
        return {
            "video_id": video_id,
            "snippets": snippets,
            "full_text": full_text,
            "snippet_count": len(snippets),
            "duration_seconds": duration_seconds,
            "language": language,
            "language_code": language_code,
            "is_generated": is_generated,
            "character_count": len(full_text),
        }
    except AttributeError:
        # Compatibility fallback for older youtube-transcript-api versions.
        pass

    try:
        raw_entries = YouTubeTranscriptApi.get_transcript(video_id, languages=language_codes)
    except Exception as exc:
        error_name = exc.__class__.__name__
        if error_name in {"TranscriptsDisabled", "NoTranscriptFound", "VideoUnavailable"}:
            raise RuntimeError(f"No usable transcript for this video ({error_name}).") from exc
        if error_name in {"RequestBlocked", "IpBlocked"}:
            raise RuntimeError(
                "YouTube blocked transcript requests from this environment (IP blocked/request blocked)."
            ) from exc
        raise RuntimeError(f"Failed to fetch YouTube transcript ({error_name}): {exc}") from exc

    snippets = _normalize_raw_entries(raw_entries)
    full_text = "\n".join(entry["text"] for entry in snippets if entry["text"])
    duration_seconds = _estimate_duration_seconds(snippets)
    return {
        "video_id": video_id,
        "snippets": snippets,
        "full_text": full_text,
        "snippet_count": len(snippets),
        "duration_seconds": duration_seconds,
        "language": "",
        "language_code": "",
        "is_generated": False,
        "character_count": len(full_text),
    }


def _normalize_fetched_snippets(fetched: Any) -> tuple[list[dict[str, object]], str, float]:
    snippets: list[dict[str, object]] = []
    for item in fetched:
        text = _safe_str(getattr(item, "text", "")).strip()
        start = _safe_float(getattr(item, "start", 0.0))
        duration = _safe_float(getattr(item, "duration", 0.0))
        snippets.append(
            {
                "text": text,
                "start": start,
                "duration": duration,
            }
        )

    full_text = "\n".join(entry["text"] for entry in snippets if entry["text"])
    duration_seconds = _estimate_duration_seconds(snippets)
    return snippets, full_text, duration_seconds


def _normalize_raw_entries(raw_entries: object) -> list[dict[str, object]]:
    if not isinstance(raw_entries, list):
        return []

    snippets: list[dict[str, object]] = []
    for entry in raw_entries:
        if not isinstance(entry, dict):
            continue
        text = _safe_str(entry.get("text", "")).strip()
        start = _safe_float(entry.get("start", 0.0))
        duration = _safe_float(entry.get("duration", 0.0))
        snippets.append(
            {
                "text": text,
                "start": start,
                "duration": duration,
            }
        )
    return snippets


def _estimate_duration_seconds(snippets: list[dict[str, object]]) -> float:
    if not snippets:
        return 0.0
    last = snippets[-1]
    return max(0.0, _safe_float(last.get("start", 0.0)) + _safe_float(last.get("duration", 0.0)))


async def _summarize_transcript(*, transcript_payload: dict[str, object], detail_level: str) -> dict[str, object]:
    settings = await load_settings()
    provider_id = settings.active_provider_id.strip()
    if not provider_id:
        raise RuntimeError("Active provider is not configured.")

    provider_config = settings.provider_configs.get(provider_id)
    if provider_config is None:
        raise RuntimeError("Active provider config is missing.")

    model_id = provider_config.model.strip()
    api_key = provider_config.api_key
    if not model_id:
        raise RuntimeError("Active provider model is missing.")
    if not api_key.strip():
        raise RuntimeError("Active provider API key is missing.")

    provider = get_provider(provider_id)
    if provider is None:
        raise RuntimeError("Active provider is unavailable.")

    full_text = _safe_str(transcript_payload.get("full_text", ""))
    text_budget = _summary_input_char_budget(detail_level)
    transcript_excerpt = _truncate_middle(full_text, text_budget)

    prompt = _build_summary_prompt(
        detail_level=detail_level,
        transcript_excerpt=transcript_excerpt,
        transcript_payload=transcript_payload,
    )
    system_prompt = (
        "You summarize YouTube transcripts. "
        "Use only the transcript content supplied. "
        "Return JSON only and no markdown."
    )

    response_text, _used_tokens = await generate_with_retries(
        provider=provider,
        prompt=prompt,
        system_prompt=system_prompt,
        model=model_id,
        api_key=api_key,
        history=[],
    )
    parsed = _parse_json_object(response_text)
    summary = _clean_text(parsed.get("summary"))
    key_points = _normalize_string_list(parsed.get("key_points"), max_items=20)

    if not summary:
        summary = _clean_text(response_text)

    return {
        "summary": summary,
        "key_points": key_points,
    }


def _build_summary_prompt(
    *,
    detail_level: str,
    transcript_excerpt: str,
    transcript_payload: dict[str, object],
) -> str:
    instruction = {
        "brief": "Return a strongly compressed overview in 3-5 sentences.",
        "standard": "Return a clear summary in about 2 short paragraphs.",
        "detailed": "Return a thorough, complete summary covering the full flow and key details.",
    }.get(detail_level, "Return a clear summary.")

    meta = {
        "video_id": _safe_str(transcript_payload.get("video_id", "")),
        "language": _safe_str(transcript_payload.get("language", "")),
        "language_code": _safe_str(transcript_payload.get("language_code", "")),
        "is_generated": bool(transcript_payload.get("is_generated", False)),
        "snippet_count": int(transcript_payload.get("snippet_count", 0) or 0),
        "duration_seconds": _safe_float(transcript_payload.get("duration_seconds", 0.0)),
        "character_count": int(transcript_payload.get("character_count", 0) or 0),
        "detail_level": detail_level,
    }

    return (
        "Summarize the transcript based only on provided transcript text.\n"
        f"{instruction}\n"
        "Return JSON only in this schema:\n"
        '{"summary":"...","key_points":["...","..."]}\n\n'
        f"Transcript metadata:\n{json.dumps(meta, ensure_ascii=True)}\n\n"
        f"Transcript text:\n{transcript_excerpt}"
    )


def _summary_input_char_budget(detail_level: str) -> int:
    if detail_level == "brief":
        return 12000
    if detail_level == "detailed":
        return 80000
    return 30000


def _truncate_middle(value: str, max_chars: int) -> str:
    text = str(value or "")
    if len(text) <= max_chars:
        return text
    if max_chars <= 200:
        return text[:max_chars]

    head_len = int(max_chars * 0.45)
    tail_len = int(max_chars * 0.45)
    middle = "\n...[transcript truncated for context budget]...\n"
    return text[:head_len] + middle + text[-tail_len:]


def _required_str(arguments: dict[str, object], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"Missing required argument '{key}'.")
    return value.strip()


def _normalize_detail_level(raw_value: object) -> str:
    value = str(raw_value or "").strip().lower()
    if value in _DETAIL_LEVELS:
        return value
    return "standard"


def _normalize_language_codes(raw_value: object) -> list[str]:
    if not isinstance(raw_value, list):
        return ["en"]

    normalized: list[str] = []
    for item in raw_value:
        if not isinstance(item, str):
            continue
        code = item.strip().lower()
        if not code:
            continue
        if code not in normalized:
            normalized.append(code)

    return normalized or ["en"]


def _extract_video_id(video_input: str) -> str:
    cleaned = str(video_input or "").strip()
    if not cleaned:
        return ""

    if _VIDEO_ID_REGEX.fullmatch(cleaned):
        return cleaned

    parsed = urlparse(cleaned)
    host = parsed.netloc.lower()
    path = parsed.path.strip("/")

    if host in {"youtu.be", "www.youtu.be"}:
        candidate = path.split("/")[0].strip()
        return candidate if _VIDEO_ID_REGEX.fullmatch(candidate) else ""

    if host in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        if path == "watch":
            query = parse_qs(parsed.query or "")
            candidate = (query.get("v") or [""])[0].strip()
            return candidate if _VIDEO_ID_REGEX.fullmatch(candidate) else ""

        parts = [segment for segment in path.split("/") if segment]
        if len(parts) >= 2 and parts[0] in {"shorts", "embed", "live", "v"}:
            candidate = parts[1].strip()
            return candidate if _VIDEO_ID_REGEX.fullmatch(candidate) else ""

    return ""


def _parse_json_object(raw_text: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw_text)
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass

    start = raw_text.find("{")
    end = raw_text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {}

    candidate = raw_text[start : end + 1]
    try:
        payload = json.loads(candidate)
        if isinstance(payload, dict):
            return payload
    except Exception:
        return {}
    return {}


def _normalize_string_list(value: object, *, max_items: int) -> list[str]:
    if not isinstance(value, list):
        return []

    normalized: list[str] = []
    for item in value:
        cleaned = _clean_text(item)
        if not cleaned:
            continue
        normalized.append(cleaned)
        if len(normalized) >= max_items:
            break
    return normalized


def _clean_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split()).strip()


def _safe_str(value: object) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return str(value)


def _safe_float(value: object) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return 0.0
    return 0.0
