"""Timed Jobs MCP plugin for creating and managing scheduled jobs."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import TimedJob, delete_timed_job, get_timed_job, list_timed_jobs, load_settings, upsert_timed_job

from .base import MCPPlugin, McpConfigField, McpToolSpec


TIMED_JOBS_MCP_ID = "timed_jobs"
_INTERVAL_VALUES = {
    "daily",
    "weekly",
    "monthly",
    "once",
    "hourly",
    "every_2_hours",
    "every_30_min",
    "every_15_min",
    "every_10_min",
    "every_5_min",
}
_UPDATABLE_FIELDS = {
    "title",
    "prompt",
    "interval",
    "start_date",
    "time_of_day",
    "enabled",
    "output_decision_enabled",
    "channels",
    "provider_id",
    "model",
}


class TimedJobsMCP(MCPPlugin):
    mcp_id = TIMED_JOBS_MCP_ID
    display_name = "Timed Jobs"
    description = "Create, inspect, update, delete, and trigger timed jobs. This tool does not block timed jobs from being executed when disabled. This mcp is for interfacing with timed jobs."

    config_fields: list[McpConfigField] = []

    def tool_specs(self) -> list[McpToolSpec]:
        selector_properties = {
            "id": {"type": "string", "minLength": 1},
            "title_exact": {"type": "string", "minLength": 1},
        }
        write_properties = {
            "title": {"type": "string"},
            "prompt": {"type": "string"},
            "interval": {
                "type": "string",
                "enum": [
                    "daily",
                    "weekly",
                    "monthly",
                    "once",
                    "hourly",
                    "every_2_hours",
                    "every_30_min",
                    "every_15_min",
                    "every_10_min",
                    "every_5_min",
                ],
            },
            "start_date": {"type": "string", "description": "YYYY-MM-DD"},
            "time_of_day": {"type": "string", "description": "HH:MM"},
            "enabled": {"type": "boolean"},
            "output_decision_enabled": {"type": "boolean"},
            "channels": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
            },
            "provider_id": {
                "type": "string",
                "description": "Optional. Leave empty to use active provider/model at runtime.",
            },
            "model": {
                "type": "string",
                "description": "Optional model for provider_id. Ignored when provider_id is empty.",
            },
        }

        return [
            McpToolSpec(
                id="timed_jobs_list_options",
                label="Timed Jobs List Options",
                description="Returns valid intervals, output channels, and server timezone defaults.",
                input_schema={"type": "object", "properties": {}},
            ),
            McpToolSpec(
                id="timed_jobs_list",
                label="Timed Jobs List",
                description="Lists timed jobs with next execution details in server timezone.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "enabled_only": {"type": "boolean"},
                    },
                },
            ),
            McpToolSpec(
                id="timed_jobs_get",
                label="Timed Jobs Get",
                description="Gets one timed job by id or exact title.",
                input_schema={
                    "type": "object",
                    "properties": selector_properties,
                },
            ),
            McpToolSpec(
                id="timed_jobs_create",
                label="Timed Jobs Create",
                description="Creates a timed job and returns the created job with next execution details.",
                input_schema={
                    "type": "object",
                    "properties": write_properties,
                    "required": ["prompt", "interval", "start_date", "time_of_day", "channels"],
                },
            ),
            McpToolSpec(
                id="timed_jobs_update",
                label="Timed Jobs Update",
                description="Updates an existing timed job by id or exact title.",
                input_schema={
                    "type": "object",
                    "properties": {
                        **selector_properties,
                        **write_properties,
                    },
                },
            ),
            McpToolSpec(
                id="timed_jobs_delete",
                label="Timed Jobs Delete",
                description="Deletes a timed job by id or exact title.",
                input_schema={
                    "type": "object",
                    "properties": selector_properties,
                },
            ),
            McpToolSpec(
                id="timed_jobs_trigger_now",
                label="Timed Jobs Trigger Now",
                description="Triggers a timed job immediately by id or exact title. This works even if the job is disabled.",

                input_schema={
                    "type": "object",
                    "properties": selector_properties,
                },
            ),
        ]

    def tool_call_system_reminder(self, tool_id: str, params: dict[str, str]) -> str:
        del params
        if tool_id in {"timed_jobs_list_options", "timed_jobs_list", "timed_jobs_get"}:
            return ""
        return (
            "Timed Jobs safety reminder:\n"
            "- Only create, update, delete, or trigger jobs explicitly requested by the user in this chat.\n"
            "- If required schedule fields are missing or ambiguous, do not guess; return structured validation details.\n"
            "- For create/update, always include next execution in the server timezone in your result.\n"
            "- Return JSON only with this shape: {\"arguments\":{...}}"
        )

    async def verify(self, params: dict[str, str]) -> tuple[bool, str]:
        del params
        return True, "Timed Jobs MCP is ready without setup."

    async def call_tool(self, tool_id: str, arguments: dict[str, object], params: dict[str, str]) -> dict[str, object]:
        del params
        if tool_id == "timed_jobs_list_options":
            return await _tool_list_options()
        if tool_id == "timed_jobs_list":
            return await _tool_list(arguments)
        if tool_id == "timed_jobs_get":
            return await _tool_get(arguments)
        if tool_id == "timed_jobs_create":
            return await _tool_create(arguments)
        if tool_id == "timed_jobs_update":
            return await _tool_update(arguments)
        if tool_id == "timed_jobs_delete":
            return await _tool_delete(arguments)
        if tool_id == "timed_jobs_trigger_now":
            return await _tool_trigger_now(arguments)
        raise RuntimeError(f"Unsupported Timed Jobs tool: {tool_id}")


async def _tool_list_options() -> dict[str, object]:
    settings = await load_settings()
    channels = _get_channel_options(settings)
    provider_options = [
        {
            "id": provider_id,
            "default_model": config.model,
        }
        for provider_id, config in settings.provider_configs.items()
    ]
    timezone_name, timezone_offset_minutes = _server_timezone_defaults()
    return {
        "ok": True,
        "intervals": [
            "daily",
            "weekly",
            "monthly",
            "once",
            "hourly",
            "every_2_hours",
            "every_30_min",
            "every_15_min",
            "every_10_min",
            "every_5_min",
        ],
        "channel_options": channels,
        "provider_options": provider_options,
        "defaults": {
            "timezone": timezone_name,
            "timezone_offset_minutes": timezone_offset_minutes,
            "provider_id": settings.active_provider_id,
            "model": settings.active_model_id,
        },
    }


async def _tool_list(arguments: dict[str, object]) -> dict[str, object]:
    enabled_only = bool(arguments.get("enabled_only", False))
    jobs = await list_timed_jobs()
    if enabled_only:
        jobs = [job for job in jobs if job.enabled]
    with_next = [_job_result_payload(job) for job in jobs]
    return {
        "ok": True,
        "count": len(with_next),
        "jobs": with_next,
    }


async def _tool_get(arguments: dict[str, object]) -> dict[str, object]:
    selected, selection_error = await _resolve_job_selector(arguments)
    if selection_error is not None:
        return selection_error
    if selected is None:
        return _validation_error(
            tool_id="timed_jobs_get",
            message="Timed job not found.",
            invalid_fields=[{"field": "id/title_exact", "reason": "No matching timed job found."}],
        )
    return {
        "ok": True,
        "job": _job_result_payload(selected),
    }


async def _tool_create(arguments: dict[str, object]) -> dict[str, object]:
    settings = await load_settings()
    channel_options = _get_channel_options(settings)

    payload: dict[str, object] = {}
    missing_fields: list[str] = []
    invalid_fields: list[dict[str, str]] = []

    title = _optional_str(arguments, "title", "")
    prompt = _optional_str(arguments, "prompt", "")
    interval = _optional_str(arguments, "interval", "")
    start_date = _optional_str(arguments, "start_date", "")
    time_of_day = _optional_str(arguments, "time_of_day", "")
    channels_raw = arguments.get("channels")
    provider_id = _optional_str(arguments, "provider_id", "").lower()
    model = _optional_str(arguments, "model", "")

    if not prompt:
        missing_fields.append("prompt")
    if not interval:
        missing_fields.append("interval")
    if not start_date:
        missing_fields.append("start_date")
    if not time_of_day:
        missing_fields.append("time_of_day")
    if not isinstance(channels_raw, list) or len(channels_raw) == 0:
        missing_fields.append("channels")

    if interval and interval not in _INTERVAL_VALUES:
        invalid_fields.append(
            {
                "field": "interval",
                "reason": "Must be one of: daily, weekly, monthly, once, hourly, every_2_hours, every_30_min, every_15_min, every_10_min, every_5_min.",
            }
        )

    if start_date and not _is_valid_iso_date(start_date):
        invalid_fields.append(
            {
                "field": "start_date",
                "reason": "Must be a valid date in YYYY-MM-DD format.",
            }
        )

    if time_of_day and not _is_valid_time_hh_mm(time_of_day):
        invalid_fields.append(
            {
                "field": "time_of_day",
                "reason": "Must be a valid time in HH:MM format.",
            }
        )

    normalized_channels, unavailable_channels, unknown_channels = _validate_channels(channels_raw, channel_options)
    if unknown_channels:
        invalid_fields.append(
            {
                "field": "channels",
                "reason": f"Unknown channel ids: {', '.join(unknown_channels)}",
            }
        )

    if model and not provider_id:
        invalid_fields.append(
            {
                "field": "model",
                "reason": "Model requires provider_id.",
            }
        )
    if provider_id and provider_id not in settings.provider_configs:
        invalid_fields.append(
            {
                "field": "provider_id",
                "reason": f"Provider '{provider_id}' is not configured.",
            }
        )
    if provider_id and not model:
        configured_provider = settings.provider_configs.get(provider_id)
        model = configured_provider.model.strip() if configured_provider is not None else ""

    if missing_fields or invalid_fields or unavailable_channels:
        return _validation_error(
            tool_id="timed_jobs_create",
            message="Cannot create timed job until missing/invalid fields are resolved.",
            missing_fields=missing_fields,
            invalid_fields=invalid_fields,
            unavailable_channels=unavailable_channels,
        )

    timezone_name, timezone_offset_minutes = _server_timezone_defaults()

    payload["title"] = title
    payload["prompt"] = prompt
    payload["interval"] = interval
    payload["start_date"] = start_date
    payload["time_of_day"] = _normalize_time_hh_mm(time_of_day)
    payload["timezone"] = timezone_name
    payload["timezone_offset_minutes"] = timezone_offset_minutes
    payload["enabled"] = bool(arguments.get("enabled", True))
    payload["output_decision_enabled"] = False
    payload["channels"] = normalized_channels
    payload["provider_id"] = provider_id
    payload["model"] = model

    created = await upsert_timed_job(payload)
    job_payload = _job_result_payload(created)
    next_details_raw = job_payload.get("next_execution")
    next_details = next_details_raw if isinstance(next_details_raw, dict) else {}
    return {
        "ok": True,
        "action": "created",
        "job": job_payload,
        "message": f"Timed job created. {next_details.get('message', '').strip()}".strip(),
    }


async def _tool_update(arguments: dict[str, object]) -> dict[str, object]:
    selected, selection_error = await _resolve_job_selector(arguments)
    if selection_error is not None:
        return selection_error
    if selected is None:
        return _validation_error(
            tool_id="timed_jobs_update",
            message="Timed job not found.",
            invalid_fields=[{"field": "id/title_exact", "reason": "No matching timed job found."}],
        )

    settings = await load_settings()
    channel_options = _get_channel_options(settings)

    update_payload: dict[str, object] = {
        "title": selected.title,
        "prompt": selected.prompt,
        "interval": selected.interval,
        "start_date": selected.start_date,
        "time_of_day": selected.time_of_day,
        "enabled": selected.enabled,
        "output_decision_enabled": selected.output_decision_enabled,
        "channels": list(selected.channels),
        "provider_id": selected.provider_id,
        "model": selected.model,
        "created_at": selected.created_at,
        "last_run_at": selected.last_run_at,
    }

    changed_fields = [field for field in _UPDATABLE_FIELDS if field in arguments]
    if not changed_fields:
        return _validation_error(
            tool_id="timed_jobs_update",
            message="No updatable fields were provided.",
            missing_fields=["at least one updatable field"],
            invalid_fields=[
                {
                    "field": "payload",
                    "reason": "Provide one or more of title, prompt, interval, start_date, time_of_day, enabled, output_decision_enabled, channels, provider_id, model.",
                }
            ],
        )

    invalid_fields: list[dict[str, str]] = []
    unavailable_channels: list[str] = []

    if "title" in arguments:
        update_payload["title"] = _optional_str(arguments, "title", "")
    if "prompt" in arguments:
        next_prompt = _optional_str(arguments, "prompt", "")
        if not next_prompt:
            invalid_fields.append({"field": "prompt", "reason": "Prompt cannot be empty."})
        update_payload["prompt"] = next_prompt
    if "interval" in arguments:
        next_interval = _optional_str(arguments, "interval", "")
        if next_interval not in _INTERVAL_VALUES:
            invalid_fields.append(
                {
                    "field": "interval",
                    "reason": "Must be one of: daily, weekly, monthly, once, hourly, every_2_hours, every_30_min, every_15_min, every_10_min, every_5_min.",
                }
            )
        else:
            update_payload["interval"] = next_interval
    if "start_date" in arguments:
        next_start_date = _optional_str(arguments, "start_date", "")
        if not _is_valid_iso_date(next_start_date):
            invalid_fields.append({"field": "start_date", "reason": "Must be a valid date in YYYY-MM-DD format."})
        else:
            update_payload["start_date"] = next_start_date
    if "time_of_day" in arguments:
        next_time = _optional_str(arguments, "time_of_day", "")
        if not _is_valid_time_hh_mm(next_time):
            invalid_fields.append({"field": "time_of_day", "reason": "Must be a valid time in HH:MM format."})
        else:
            update_payload["time_of_day"] = _normalize_time_hh_mm(next_time)
    if "enabled" in arguments:
        update_payload["enabled"] = bool(arguments.get("enabled", False))
    if "output_decision_enabled" in arguments:
        update_payload["output_decision_enabled"] = bool(arguments.get("output_decision_enabled", False))
    if "provider_id" in arguments:
        update_payload["provider_id"] = _optional_str(arguments, "provider_id", "").lower()
    if "model" in arguments:
        update_payload["model"] = _optional_str(arguments, "model", "")

    candidate_provider_id = str(update_payload.get("provider_id", "")).strip().lower()
    candidate_model = str(update_payload.get("model", "")).strip()
    if candidate_model and not candidate_provider_id:
        invalid_fields.append({"field": "model", "reason": "Model requires provider_id."})
    if candidate_provider_id and candidate_provider_id not in settings.provider_configs:
        invalid_fields.append(
            {
                "field": "provider_id",
                "reason": f"Provider '{candidate_provider_id}' is not configured.",
            }
        )
    if candidate_provider_id and not candidate_model:
        configured_provider = settings.provider_configs.get(candidate_provider_id)
        candidate_model = configured_provider.model.strip() if configured_provider is not None else ""

    update_payload["provider_id"] = candidate_provider_id
    update_payload["model"] = candidate_model

    timezone_name, timezone_offset_minutes = _server_timezone_defaults()
    update_payload["timezone"] = timezone_name
    update_payload["timezone_offset_minutes"] = timezone_offset_minutes

    if "channels" in arguments:
        normalized_channels, unavailable_channels, unknown_channels = _validate_channels(arguments.get("channels"), channel_options)
        if unknown_channels:
            invalid_fields.append(
                {
                    "field": "channels",
                    "reason": f"Unknown channel ids: {', '.join(unknown_channels)}",
                }
            )
        elif not normalized_channels:
            invalid_fields.append(
                {
                    "field": "channels",
                    "reason": "At least one valid output channel is required.",
                }
            )
        else:
            update_payload["channels"] = normalized_channels

    if unavailable_channels or invalid_fields:
        return _validation_error(
            tool_id="timed_jobs_update",
            message="Cannot update timed job until invalid fields are resolved.",
            invalid_fields=invalid_fields,
            unavailable_channels=unavailable_channels,
        )

    updated = await upsert_timed_job(update_payload, timed_job_id=selected.id)
    job_payload = _job_result_payload(updated)
    next_details_raw = job_payload.get("next_execution")
    next_details = next_details_raw if isinstance(next_details_raw, dict) else {}
    return {
        "ok": True,
        "action": "updated",
        "job": job_payload,
        "message": f"Timed job updated. {next_details.get('message', '').strip()}".strip(),
    }


async def _tool_delete(arguments: dict[str, object]) -> dict[str, object]:
    selected, selection_error = await _resolve_job_selector(arguments)
    if selection_error is not None:
        return selection_error
    if selected is None:
        return _validation_error(
            tool_id="timed_jobs_delete",
            message="Timed job not found.",
            invalid_fields=[{"field": "id/title_exact", "reason": "No matching timed job found."}],
        )

    deleted = await delete_timed_job(selected.id)
    return {
        "ok": bool(deleted),
        "action": "deleted",
        "deleted": bool(deleted),
        "job": {
            "id": selected.id,
            "title": selected.title,
        },
        "message": "Timed job deleted." if deleted else "Timed job was not deleted.",
    }


async def _tool_trigger_now(arguments: dict[str, object]) -> dict[str, object]:
    selected, selection_error = await _resolve_job_selector(arguments)
    if selection_error is not None:
        return selection_error
    if selected is None:
        return _validation_error(
            tool_id="timed_jobs_trigger_now",
            message="Timed job not found.",
            invalid_fields=[{"field": "id/title_exact", "reason": "No matching timed job found."}],
        )

    ok = await _trigger_job_now(selected.id)
    refreshed = await get_timed_job(selected.id)
    payload_job = _job_result_payload(refreshed or selected)
    return {
        "ok": bool(ok),
        "action": "triggered_now",
        "job": payload_job,
        "message": "Timed job triggered now." if ok else "Timed job could not be triggered.",
    }


async def _resolve_job_selector(arguments: dict[str, object]) -> tuple[TimedJob | None, dict[str, object] | None]:
    job_id = _optional_str(arguments, "id", "")
    title_exact = " ".join(_optional_str(arguments, "title_exact", "").split())

    if not job_id and not title_exact:
        return (
            None,
            _validation_error(
                tool_id="timed_jobs_selector",
                message="Missing selector. Provide id or title_exact.",
                missing_fields=["id or title_exact"],
            ),
        )

    if job_id:
        found = await get_timed_job(job_id)
        if found is None:
            return None, _validation_error(
                tool_id="timed_jobs_selector",
                message="No timed job found for the provided id.",
                invalid_fields=[{"field": "id", "reason": "No timed job exists with this id."}],
            )
        return found, None

    jobs = await list_timed_jobs()
    matches = [
        job
        for job in jobs
        if " ".join(job.title.split()).strip().casefold() == title_exact.casefold()
    ]
    if not matches:
        return None, _validation_error(
            tool_id="timed_jobs_selector",
            message="No timed job found for the provided title_exact.",
            invalid_fields=[{"field": "title_exact", "reason": "No timed job exists with this exact title."}],
        )
    if len(matches) > 1:
        return None, _validation_error(
            tool_id="timed_jobs_selector",
            message="title_exact is ambiguous. Multiple timed jobs have this exact title.",
            ambiguous_selection={
                "field": "title_exact",
                "title_exact": title_exact,
                "candidates": [
                    {
                        "id": job.id,
                        "title": job.title,
                        "next_run_at": job.next_run_at,
                    }
                    for job in matches
                ],
            },
        )
    return matches[0], None


def _validation_error(
    *,
    tool_id: str,
    message: str,
    missing_fields: list[str] | None = None,
    invalid_fields: list[dict[str, str]] | None = None,
    unavailable_channels: list[str] | None = None,
    ambiguous_selection: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "ok": False,
        "tool_id": tool_id,
        "error_type": "validation_error",
        "message": message,
        "missing_fields": missing_fields or [],
        "invalid_fields": invalid_fields or [],
        "unavailable_channels": unavailable_channels or [],
        "ambiguous_selection": ambiguous_selection or {},
    }


def _validate_channels(raw_channels: object, channel_options: list[dict[str, object]]) -> tuple[list[str], list[str], list[str]]:
    if not isinstance(raw_channels, list):
        return [], [], []

    known_channels = {str(entry.get("id", "")).strip().lower() for entry in channel_options}
    available_channels = {
        str(entry.get("id", "")).strip().lower()
        for entry in channel_options
        if bool(entry.get("available", False))
    }

    normalized: list[str] = []
    unavailable: list[str] = []
    unknown: list[str] = []
    for entry in raw_channels:
        channel_id = str(entry).strip().lower()
        if not channel_id:
            continue
        if channel_id not in known_channels:
            if channel_id not in unknown:
                unknown.append(channel_id)
            continue
        if channel_id not in available_channels:
            if channel_id not in unavailable:
                unavailable.append(channel_id)
            continue
        if channel_id not in normalized:
            normalized.append(channel_id)

    return normalized, unavailable, unknown


def _server_timezone_defaults() -> tuple[str, int]:
    now_local = datetime.now().astimezone()
    offset_delta = now_local.utcoffset() or timedelta(minutes=0)
    offset_minutes = int(offset_delta.total_seconds() // 60)

    timezone_name = ""
    tzinfo = now_local.tzinfo
    zoneinfo_key = getattr(tzinfo, "key", "")
    if isinstance(zoneinfo_key, str) and zoneinfo_key.strip():
        timezone_name = zoneinfo_key.strip()
    else:
        label = now_local.tzname() or ""
        timezone_name = label.strip()

    if not timezone_name:
        timezone_name = _offset_timezone_name(offset_minutes)

    return timezone_name, max(-840, min(840, offset_minutes))


def _job_result_payload(job: TimedJob) -> dict[str, object]:
    next_execution = _next_execution_details(job)
    payload = job.model_dump()
    payload["next_execution"] = next_execution
    return payload


def _next_execution_details(job: TimedJob) -> dict[str, object]:
    raw_next = str(job.next_run_at or "").strip()
    if not raw_next:
        reason = "No next execution is scheduled."
        if not job.enabled:
            reason = "No next execution is scheduled because this timed job is disabled."
        elif job.interval == "once" and str(job.last_run_at or "").strip():
            reason = "No next execution is scheduled because this one-time job already ran."
        return {
            "status": "not_scheduled",
            "next_run_at_utc": "",
            "next_run_at_server_timezone": "",
            "timezone": _server_timezone_defaults()[0],
            "message": reason,
        }

    try:
        parsed = datetime.fromisoformat(raw_next)
    except ValueError:
        return {
            "status": "scheduled",
            "next_run_at_utc": raw_next,
            "next_run_at_server_timezone": raw_next,
            "timezone": _server_timezone_defaults()[0],
            "message": f"Next execution in server timezone: {raw_next}.",
        }

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    server_timezone_name, server_timezone_offset = _server_timezone_defaults()
    tz = _job_timezone(server_timezone_name, server_timezone_offset)
    local_value = parsed.astimezone(tz).isoformat(timespec="minutes")
    return {
        "status": "scheduled",
        "next_run_at_utc": parsed.astimezone(timezone.utc).isoformat(timespec="minutes"),
        "next_run_at_server_timezone": local_value,
        "timezone": server_timezone_name,
        "message": f"Next execution in server timezone: {local_value} ({server_timezone_name}).",
    }


def _job_timezone(name: str, offset_minutes: int) -> timezone | ZoneInfo:
    cleaned_name = str(name or "").strip()
    if cleaned_name and cleaned_name.upper() != "UTC":
        try:
            return ZoneInfo(cleaned_name)
        except ZoneInfoNotFoundError:
            pass

    safe_offset = max(-840, min(840, int(offset_minutes)))
    return timezone(timedelta(minutes=safe_offset))


def _offset_timezone_name(offset_minutes: int) -> str:
    safe_offset = max(-840, min(840, int(offset_minutes)))
    sign = "+" if safe_offset >= 0 else "-"
    absolute = abs(safe_offset)
    hours = absolute // 60
    minutes = absolute % 60
    return f"UTC{sign}{hours:02d}:{minutes:02d}"


def _is_valid_iso_date(value: str) -> bool:
    cleaned = str(value).strip()
    if not cleaned:
        return False
    try:
        date.fromisoformat(cleaned)
    except ValueError:
        return False
    return True


def _is_valid_time_hh_mm(value: str) -> bool:
    cleaned = str(value).strip()
    if not cleaned:
        return False
    try:
        parsed = time.fromisoformat(cleaned)
    except ValueError:
        return False
    return 0 <= parsed.hour <= 23 and 0 <= parsed.minute <= 59


def _normalize_time_hh_mm(value: str) -> str:
    parsed = time.fromisoformat(str(value).strip())
    return f"{parsed.hour:02d}:{parsed.minute:02d}"


def _optional_str(arguments: dict[str, object], key: str, default: str = "") -> str:
    value = arguments.get(key)
    if isinstance(value, str):
        return value.strip()
    return default


def _get_channel_options(settings: Any) -> list[dict[str, object]]:
    from app.timed_jobs import get_timed_job_channel_options

    return get_timed_job_channel_options(settings)


async def _trigger_job_now(timed_job_id: str) -> bool:
    from app.timed_jobs import trigger_timed_job_now

    return await trigger_timed_job_now(timed_job_id)
