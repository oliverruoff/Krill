"""Pi-backed agent runtime bridge for Krill chat execution."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shlex
import sys
from pathlib import Path
from typing import Any, Awaitable, Callable, TypedDict, cast

from app.config import BASE_DIR, DATA_DIR, McpConfig, Settings
from app.mcps.base import MCPPlugin, McpConfigField
from app.mcps.registry import get_all_mcps

from .execution import CancellationToken, ExecutionEvent, execution_event
from .runtime_context import get_runtime_context


logger = logging.getLogger(__name__)


class ToolUsageEntry(TypedDict):
    mcp_id: str
    mcp_label: str
    tool_id: str
    tool_label: str


class SystemTraceEntry(TypedDict):
    system_type: str
    content: str


class OrchestrationResult(TypedDict):
    text: str
    used_tokens: int | None
    used_mcp_tools: list[ToolUsageEntry]
    system_trace_messages: list[SystemTraceEntry]
    execution_events: list[ExecutionEvent]


class PiProviderConfig(TypedDict):
    provider: str
    model: str
    api_key: str


class PiToolEntry(TypedDict):
    mcp_id: str
    mcp_label: str
    tool_id: str
    tool_label: str
    tool_description: str
    input_schema: dict[str, object]
    plugin: MCPPlugin
    config: McpConfig


ExecutionEventCallback = Callable[[ExecutionEvent], Awaitable[None]]


_PI_NATIVE_MCP_IDS = {
    "git_ops",
    "opencode",
    "shell_access",
}
_PROVIDER_MAP = {
    "gemini": ("google", "GEMINI_API_KEY"),
    "openai": ("openai", "OPENAI_API_KEY"),
    "openrouter": ("openrouter", "OPENROUTER_API_KEY"),
    "minimax": ("minimax", "MINIMAX_API_KEY"),
}
_SIDE_CAR_DIR = BASE_DIR / "pi-sidecar"
_SIDE_CAR_ENTRYPOINT = _SIDE_CAR_DIR / "index.js"


async def generate_with_pi(
    *,
    settings: Settings,
    prompt: str,
    system_prompt: str,
    model: str,
    api_key: str,
    history: list[dict[str, str]],
    provider_id: str = "",
    max_tool_recursion: int = 0,
    tool_timeout_seconds: int = 90,
    on_execution_event: ExecutionEventCallback | None = None,
    cancellation_token: CancellationToken | None = None,
    **_: Any,
) -> OrchestrationResult:
    del history, max_tool_recursion
    cancel_token = cancellation_token or CancellationToken()
    provider = _resolve_pi_provider(settings=settings, provider_id=provider_id, model=model, api_key=api_key)
    tool_entries = collect_pi_krill_tools(settings)
    request = _build_sidecar_request(
        prompt=prompt,
        system_prompt=system_prompt,
        provider=provider,
        tool_entries=tool_entries,
    )

    execution_events: list[ExecutionEvent] = []
    system_trace_messages: list[SystemTraceEntry] = []
    used_tools: list[ToolUsageEntry] = []

    async def emit_event(event: ExecutionEvent) -> None:
        if cancel_token.is_cancelled and event.get("event_type") != "task_cancelled":
            return
        execution_events.append(event)
        if on_execution_event is not None:
            await on_execution_event(event)

    await emit_event(execution_event("task_started", message="Starting Pi agent runtime.", stage="planning"))
    system_trace_messages.append({"system_type": "runtime_system_prompt", "content": system_prompt})

    process = await _start_sidecar_process(provider)
    write_lock = asyncio.Lock()
    tool_tasks: set[asyncio.Task[None]] = set()
    result_payload: dict[str, object] | None = None
    error_message = ""

    async def send(payload: dict[str, object]) -> None:
        if process.stdin is None:
            raise RuntimeError("Pi sidecar stdin is unavailable.")
        encoded = (json.dumps(payload, ensure_ascii=True) + "\n").encode("utf-8")
        async with write_lock:
            process.stdin.write(encoded)
            await process.stdin.drain()

    async def run_tool_call(payload: dict[str, object]) -> None:
        call_id = str(payload.get("id", "")).strip()
        mcp_id = str(payload.get("mcp_id", "")).strip()
        tool_id = str(payload.get("tool_id", "")).strip()
        arguments = payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}
        entry = _find_tool_entry(tool_entries, mcp_id=mcp_id, tool_id=tool_id)
        if not call_id:
            return
        if entry is None:
            await send(
                {
                    "type": "tool_result",
                    "id": call_id,
                    "ok": False,
                    "error": f"Krill MCP tool is not available: {mcp_id}.{tool_id}",
                }
            )
            return

        usage = {
            "mcp_id": entry["mcp_id"],
            "mcp_label": entry["mcp_label"],
            "tool_id": entry["tool_id"],
            "tool_label": entry["tool_label"],
        }
        if usage not in used_tools:
            used_tools.append(usage)

        await emit_event(
            execution_event(
                "tool_call_started",
                message=f"Running {entry['tool_label']} with {entry['mcp_label']}.",
                stage=_stage_for_mcp_id(mcp_id),
                mcp_id=mcp_id,
                mcp_label=entry["mcp_label"],
                tool_id=tool_id,
                tool_label=entry["tool_label"],
                call_id=call_id,
            )
        )
        try:
            cancel_token.raise_if_cancelled()
            result = await asyncio.wait_for(
                entry["plugin"].call_tool(tool_id, cast(dict[str, object], arguments), entry["config"].params),
                timeout=max(5, min(300, int(tool_timeout_seconds))),
            )
            await send({"type": "tool_result", "id": call_id, "ok": True, "result": result})
            await emit_event(
                execution_event(
                    "tool_call_completed",
                    message=f"Finished {entry['tool_label']}.",
                    stage=_stage_for_mcp_id(mcp_id),
                    mcp_id=mcp_id,
                    mcp_label=entry["mcp_label"],
                    tool_id=tool_id,
                    tool_label=entry["tool_label"],
                    call_id=call_id,
                )
            )
        except Exception as exc:  # noqa: BLE001 - tool errors are returned to Pi as structured failures
            logger.exception("Pi MCP callback failed for %s.%s", mcp_id, tool_id)
            await send({"type": "tool_result", "id": call_id, "ok": False, "error": str(exc)})
            await emit_event(
                execution_event(
                    "tool_call_failed",
                    message=f"{entry['tool_label']} failed: {exc}",
                    stage=_stage_for_mcp_id(mcp_id),
                    mcp_id=mcp_id,
                    mcp_label=entry["mcp_label"],
                    tool_id=tool_id,
                    tool_label=entry["tool_label"],
                    call_id=call_id,
                )
            )

    async def watch_cancellation() -> None:
        await cancel_token.wait()
        if process.returncode is None:
            process.terminate()

    cancel_task = asyncio.create_task(watch_cancellation())

    try:
        await send({"type": "run", "request": request})
        if process.stdout is None:
            raise RuntimeError("Pi sidecar stdout is unavailable.")
        while True:
            cancel_token.raise_if_cancelled()
            raw_line = await process.stdout.readline()
            if not raw_line:
                break
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("Ignoring non-JSON Pi sidecar output: %s", line[:500])
                continue

            payload_type = str(payload.get("type", "")).strip()
            if payload_type == "event":
                event = _map_pi_event(payload.get("event"))
                if event is not None:
                    await emit_event(event)
                    system_trace_messages.append(
                        {
                            "system_type": f"execution_{event['event_type']}",
                            "content": str(event.get("message", "")),
                        }
                    )
                continue
            if payload_type == "tool_call":
                task = asyncio.create_task(run_tool_call(cast(dict[str, object], payload)))
                tool_tasks.add(task)
                task.add_done_callback(tool_tasks.discard)
                continue
            if payload_type == "result":
                result_payload = cast(dict[str, object], payload)
                break
            if payload_type == "error":
                error_message = str(payload.get("error", "")).strip() or "Pi sidecar failed."
                break

        if tool_tasks:
            await asyncio.gather(*tool_tasks, return_exceptions=True)
        await process.wait()
    except asyncio.CancelledError:
        cancel_token.cancel("Execution interrupted.")
        if process.returncode is None:
            process.terminate()
        await emit_event(execution_event("task_cancelled", message="Stopped Pi agent runtime.", stage="finalizing"))
        raise
    finally:
        cancel_task.cancel()
        if process.returncode is None and (error_message or result_payload is None):
            process.terminate()
        try:
            await process.wait()
        except Exception:
            pass

    if error_message:
        raise RuntimeError(error_message)
    if result_payload is None:
        stderr_text = ""
        if process.stderr is not None:
            raw_stderr = await process.stderr.read()
            stderr_text = raw_stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(stderr_text or "Pi sidecar exited without a result.")

    await emit_event(execution_event("task_completed", message="Completed the task.", stage="finalizing"))
    stats = result_payload.get("stats") if isinstance(result_payload.get("stats"), dict) else {}
    tokens = cast(dict[str, object], stats).get("tokens") if isinstance(stats, dict) else {}
    used_tokens = None
    if isinstance(tokens, dict) and isinstance(tokens.get("total"), int):
        used_tokens = int(tokens["total"])

    return {
        "text": str(result_payload.get("text", "")).strip(),
        "used_tokens": used_tokens,
        "used_mcp_tools": used_tools,
        "system_trace_messages": system_trace_messages,
        "execution_events": execution_events,
    }


def collect_pi_krill_tools(settings: Settings) -> list[PiToolEntry]:
    entries: list[PiToolEntry] = []
    source_user_role = str(get_runtime_context().get("source_user_role", "")).strip().lower()
    for mcp_id, plugin in get_all_mcps().items():
        if mcp_id in _PI_NATIVE_MCP_IDS:
            continue
        if not _runtime_allows_mcp(mcp_id):
            continue
        raw_config = settings.mcp_configs.get(mcp_id)
        if source_user_role == "assistant_usage" and raw_config is None:
            continue
        config = raw_config or McpConfig(enabled=bool(getattr(plugin, "default_enabled", False)), params={})
        if not config.enabled:
            continue
        if _missing_required_param_ids(plugin.config_fields, config):
            continue

        tool_specs = plugin.tool_specs()
        if hasattr(plugin, "tool_specs_for_config"):
            try:
                maybe_specs = getattr(plugin, "tool_specs_for_config")(config.params)
                if isinstance(maybe_specs, list):
                    tool_specs = maybe_specs
            except Exception:
                logger.exception("Could not collect config-specific tool specs for MCP %s", mcp_id)

        for tool in tool_specs:
            entries.append(
                {
                    "mcp_id": mcp_id,
                    "mcp_label": plugin.display_name,
                    "tool_id": tool.id,
                    "tool_label": tool.label,
                    "tool_description": tool.description,
                    "input_schema": tool.input_schema,
                    "plugin": plugin,
                    "config": config,
                }
            )
    return entries


def _resolve_pi_provider(*, settings: Settings, provider_id: str, model: str, api_key: str) -> PiProviderConfig:
    active_provider_id = provider_id.strip() if provider_id.strip() else settings.active_provider_id
    mapped = _PROVIDER_MAP.get(active_provider_id)
    if mapped is None:
        supported = ", ".join(sorted(_PROVIDER_MAP))
        raise RuntimeError(
            f"Provider '{active_provider_id}' is not supported by the Pi runtime bridge yet. "
            f"Supported Krill providers: {supported}."
        )
    provider_config = settings.provider_configs.get(active_provider_id)
    model_id = model.strip() if model.strip() else (provider_config.model if provider_config is not None else "")
    api_key_value = api_key if api_key.strip() else (provider_config.api_key if provider_config is not None else "")
    if not model_id:
        raise RuntimeError(f"Provider '{active_provider_id}' has no model configured for Pi.")
    if not api_key_value:
        env_name = mapped[1]
        api_key_value = os.getenv(env_name, "")
    if not api_key_value:
        raise RuntimeError(f"Provider '{active_provider_id}' has no API key configured for Pi.")
    return {"provider": mapped[0], "model": model_id, "api_key": api_key_value}


def _build_sidecar_request(
    *,
    prompt: str,
    system_prompt: str,
    provider: PiProviderConfig,
    tool_entries: list[PiToolEntry],
) -> dict[str, object]:
    runtime_context = get_runtime_context()
    source_channel = str(runtime_context.get("source_channel", "") or "gateway").strip() or "gateway"
    source_chat_id = str(runtime_context.get("source_chat_id", "") or "").strip()
    source_request_id = str(runtime_context.get("source_request_id", "") or "").strip()
    session_key = f"{source_channel}:{source_chat_id or source_request_id or 'default'}"
    return {
        "cwd": str(BASE_DIR),
        "pi_data_dir": str((DATA_DIR / "pi_sessions").resolve()),
        "session_key": session_key,
        "message": prompt,
        "system_prompt": system_prompt,
        "provider": provider,
        "krill_tools": [_serialize_tool_entry(entry) for entry in tool_entries],
    }


def _serialize_tool_entry(entry: PiToolEntry) -> dict[str, object]:
    return {
        "mcp_id": entry["mcp_id"],
        "mcp_label": entry["mcp_label"],
        "tool_id": entry["tool_id"],
        "tool_label": entry["tool_label"],
        "tool_description": entry["tool_description"],
        "input_schema": entry["input_schema"],
    }


async def _start_sidecar_process(provider: PiProviderConfig) -> asyncio.subprocess.Process:
    command = os.getenv("KRILL_PI_SIDECAR_COMMAND", "").strip()
    if command:
        args = shlex.split(command)
    else:
        args = [_node_executable(), str(_SIDE_CAR_ENTRYPOINT)]
    env = os.environ.copy()
    env[_provider_env_name(provider["provider"])] = provider["api_key"]
    return await asyncio.create_subprocess_exec(
        *args,
        cwd=str(BASE_DIR),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )


def _node_executable() -> str:
    return "node.exe" if sys.platform.startswith("win") else "node"


def _provider_env_name(provider: str) -> str:
    return {
        "google": "GEMINI_API_KEY",
        "openai": "OPENAI_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
        "minimax": "MINIMAX_API_KEY",
    }.get(provider, "KRILL_PI_API_KEY")


def _find_tool_entry(tool_entries: list[PiToolEntry], *, mcp_id: str, tool_id: str) -> PiToolEntry | None:
    for entry in tool_entries:
        if entry["mcp_id"] == mcp_id and entry["tool_id"] == tool_id:
            return entry
    return None


def _runtime_allows_mcp(mcp_id: str) -> bool:
    runtime_context = get_runtime_context()
    source_user_role = str(runtime_context.get("source_user_role", "")).strip().lower()
    if source_user_role != "assistant_usage":
        return True
    allowed_mcp_ids = {
        str(item).strip()
        for item in runtime_context.get("allowed_mcp_ids", [])
        if str(item).strip()
    }
    return str(mcp_id or "").strip() in allowed_mcp_ids


def _missing_required_param_ids(config_fields: list[McpConfigField], config: McpConfig) -> list[str]:
    missing: list[str] = []
    for field in config_fields:
        if not field.required:
            continue
        value = config.params.get(field.id, "")
        if not isinstance(value, str) or not value.strip():
            missing.append(field.id)
    return missing


def _stage_for_mcp_id(mcp_id: str) -> str:
    normalized = str(mcp_id or "").strip().lower()
    if normalized in {"google_services", "brave_search", "browser_control", "youtube_summarizer", "unifi_network"}:
        return "fetching"
    if normalized in {"scripts"}:
        return "updating"
    if normalized in {"home_assistant", "whatsapp", "brain_access", "timed_jobs", "text_to_speech"}:
        return "applying"
    return "working"


def _map_pi_event(raw_event: object) -> ExecutionEvent | None:
    if not isinstance(raw_event, dict):
        return None
    event_type = str(raw_event.get("type", "")).strip()
    if event_type == "agent_start":
        return execution_event("task_started", message="Pi is working.", stage="planning")
    if event_type == "agent_end":
        return execution_event("task_completed", message="Pi finished the agent run.", stage="finalizing")
    if event_type == "tool_execution_start":
        tool_name = str(raw_event.get("toolName", "") or "tool").strip()
        return execution_event(
            "tool_call_started",
            message=f"Running {tool_name}.",
            stage="working",
            tool_id=tool_name,
            tool_label=tool_name,
            call_id=str(raw_event.get("toolCallId", "")),
        )
    if event_type == "tool_execution_update":
        tool_name = str(raw_event.get("toolName", "") or "tool").strip()
        return execution_event(
            "tool_call_progress",
            message=f"{tool_name} is still running.",
            stage="working",
            tool_id=tool_name,
            tool_label=tool_name,
            call_id=str(raw_event.get("toolCallId", "")),
        )
    if event_type == "tool_execution_end":
        tool_name = str(raw_event.get("toolName", "") or "tool").strip()
        is_error = bool(raw_event.get("isError", False))
        return execution_event(
            "tool_call_failed" if is_error else "tool_call_completed",
            message=f"{tool_name} {'failed' if is_error else 'finished'}.",
            stage="working",
            tool_id=tool_name,
            tool_label=tool_name,
            call_id=str(raw_event.get("toolCallId", "")),
        )
    if event_type == "compaction_start":
        return execution_event("compaction_started", message="Pi is compacting context.", stage="planning")
    if event_type == "compaction_end":
        return execution_event("compaction_completed", message="Pi compacted context.", stage="planning")
    if event_type == "auto_retry_start":
        return execution_event("retry_started", message="Pi is retrying after a transient error.", stage="working")
    if event_type == "auto_retry_end":
        success = bool(raw_event.get("success", False))
        return execution_event(
            "retry_completed",
            message="Pi retry succeeded." if success else "Pi retry finished with an error.",
            stage="working",
        )
    return None
