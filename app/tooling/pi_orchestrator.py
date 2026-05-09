"""Pi-backed agent runtime bridge for Krill chat execution."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shlex
import sys
import time
import uuid
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
_PI_MANAGER: "PiSidecarManager | None" = None


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
    del max_tool_recursion
    cancel_token = cancellation_token or CancellationToken()
    provider = _resolve_pi_provider(settings=settings, provider_id=provider_id, model=model, api_key=api_key)
    tool_entries = collect_pi_krill_tools(settings)
    request = _build_sidecar_request(
        prompt=prompt,
        system_prompt=system_prompt,
        history=history,
        provider=provider,
        tool_entries=tool_entries,
    )
    return await get_pi_sidecar_manager().run(
        request=request,
        provider=provider,
        system_prompt=system_prompt,
        tool_entries=tool_entries,
        tool_timeout_seconds=tool_timeout_seconds,
        on_execution_event=on_execution_event,
        cancellation_token=cancel_token,
    )


async def start_pi_runtime() -> None:
    await get_pi_sidecar_manager().start(prewarm=True)


async def stop_pi_runtime() -> None:
    manager = _PI_MANAGER
    if manager is not None:
        await manager.stop()


def get_pi_sidecar_manager() -> "PiSidecarManager":
    global _PI_MANAGER
    if _PI_MANAGER is None:
        _PI_MANAGER = PiSidecarManager()
    return _PI_MANAGER


class PiActiveRun:
    def __init__(
        self,
        *,
        request_id: str,
        manager: "PiSidecarManager",
        system_prompt: str,
        tool_entries: list[PiToolEntry],
        tool_timeout_seconds: int,
        on_execution_event: ExecutionEventCallback | None,
        cancellation_token: CancellationToken,
    ) -> None:
        self.request_id = request_id
        self.manager = manager
        self.tool_entries = tool_entries
        self.tool_timeout_seconds = tool_timeout_seconds
        self.on_execution_event = on_execution_event
        self.cancellation_token = cancellation_token
        self.future: asyncio.Future[dict[str, object]] = asyncio.get_running_loop().create_future()
        self.execution_events: list[ExecutionEvent] = []
        self.system_trace_messages: list[SystemTraceEntry] = [
            {"system_type": "runtime_system_prompt", "content": system_prompt}
        ]
        self.used_tools: list[ToolUsageEntry] = []
        self.tool_tasks: set[asyncio.Task[None]] = set()

    async def emit_event(self, event: ExecutionEvent) -> None:
        if self.cancellation_token.is_cancelled and event.get("event_type") != "task_cancelled":
            return
        self.execution_events.append(event)
        if on_execution_event := self.on_execution_event:
            await on_execution_event(event)

    async def handle_pi_event(self, raw_event: object) -> None:
        event = _map_pi_event(raw_event)
        if event is None:
            return
        await self.emit_event(event)
        self.system_trace_messages.append(
            {
                "system_type": f"execution_{event['event_type']}",
                "content": str(event.get("message", "")),
            }
        )

    def handle_tool_call(self, payload: dict[str, object]) -> None:
        task = asyncio.create_task(self._run_tool_call(payload))
        self.tool_tasks.add(task)
        task.add_done_callback(self.tool_tasks.discard)

    async def wait_for_tools(self) -> None:
        if self.tool_tasks:
            await asyncio.gather(*self.tool_tasks, return_exceptions=True)

    async def _run_tool_call(self, payload: dict[str, object]) -> None:
        call_id = str(payload.get("id", "")).strip()
        mcp_id = str(payload.get("mcp_id", "")).strip()
        tool_id = str(payload.get("tool_id", "")).strip()
        arguments = payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}
        entry = _find_tool_entry(self.tool_entries, mcp_id=mcp_id, tool_id=tool_id)
        if not call_id:
            return
        if entry is None:
            await self.manager.send(
                {
                    "type": "tool_result",
                    "request_id": self.request_id,
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
        if usage not in self.used_tools:
            self.used_tools.append(usage)

        await self.emit_event(
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
            self.cancellation_token.raise_if_cancelled()
            result = await asyncio.wait_for(
                entry["plugin"].call_tool(tool_id, cast(dict[str, object], arguments), entry["config"].params),
                timeout=max(5, min(300, int(self.tool_timeout_seconds))),
            )
            await self.manager.send(
                {"type": "tool_result", "request_id": self.request_id, "id": call_id, "ok": True, "result": result}
            )
            await self.emit_event(
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
            await self.manager.send(
                {"type": "tool_result", "request_id": self.request_id, "id": call_id, "ok": False, "error": str(exc)}
            )
            await self.emit_event(
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


class PiSidecarManager:
    def __init__(self) -> None:
        self._process: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._write_lock = asyncio.Lock()
        self._start_lock = asyncio.Lock()
        self._active_runs: dict[str, PiActiveRun] = {}
        self._pending_health: dict[str, asyncio.Future[None]] = {}
        self._last_start_error = ""

    async def start(self, *, prewarm: bool = False) -> None:
        async with self._start_lock:
            if self._process is not None and self._process.returncode is None:
                if prewarm:
                    await self._health_check()
                return
            self._process = await _start_sidecar_process()
            self._reader_task = asyncio.create_task(self._reader_loop())
            self._last_start_error = ""
            if prewarm:
                try:
                    await self._health_check()
                except Exception as exc:  # noqa: BLE001 - startup should continue but remember the issue
                    self._last_start_error = str(exc)
                    logger.exception("Pi sidecar prewarm failed")

    async def stop(self) -> None:
        process = self._process
        if process is not None and process.returncode is None:
            try:
                await self.send({"type": "shutdown"})
                await asyncio.wait_for(process.wait(), timeout=5)
            except Exception:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=5)
                except Exception:
                    process.kill()
        if self._reader_task is not None:
            self._reader_task.cancel()
        self._process = None
        self._reader_task = None

    async def run(
        self,
        *,
        request: dict[str, object],
        provider: PiProviderConfig,
        system_prompt: str,
        tool_entries: list[PiToolEntry],
        tool_timeout_seconds: int,
        on_execution_event: ExecutionEventCallback | None,
        cancellation_token: CancellationToken,
    ) -> OrchestrationResult:
        await self.start(prewarm=False)
        if self._last_start_error:
            raise RuntimeError(f"Pi runtime failed to prewarm: {self._last_start_error}")
        request_id = str(get_runtime_context().get("source_request_id", "") or "").strip() or uuid.uuid4().hex
        if request_id in self._active_runs:
            request_id = f"{request_id}-{uuid.uuid4().hex}"
        request["request_id"] = request_id
        run = PiActiveRun(
            request_id=request_id,
            manager=self,
            system_prompt=system_prompt,
            tool_entries=tool_entries,
            tool_timeout_seconds=tool_timeout_seconds,
            on_execution_event=on_execution_event,
            cancellation_token=cancellation_token,
        )
        self._active_runs[request_id] = run

        async def watch_cancellation() -> None:
            await cancellation_token.wait()
            if not run.future.done():
                await self.send({"type": "cancel", "request_id": request_id})
                run.future.set_exception(asyncio.CancelledError(cancellation_token.reason or "Execution cancelled."))

        cancel_task = asyncio.create_task(watch_cancellation())
        session_completion_task = asyncio.create_task(self._watch_session_completion(request=request, run=run))
        restart_sidecar_after_result = False
        try:
            await self.send({"type": "run", "request_id": request_id, "request": request})
            run_timeout_seconds = max(30, min(300, int(tool_timeout_seconds) * 2))
            try:
                result_payload = await asyncio.wait_for(run.future, timeout=run_timeout_seconds)
            except asyncio.TimeoutError as exc:
                await self._terminate_sidecar()
                raise RuntimeError(
                    f"Pi runtime did not finish within {run_timeout_seconds} seconds. "
                    "The run was stopped so the chat does not stay stuck."
                ) from exc
            restart_sidecar_after_result = bool(result_payload.pop("_restart_sidecar", False))
        except asyncio.CancelledError:
            cancellation_token.cancel("Execution interrupted.")
            await run.emit_event(execution_event("task_cancelled", message="Stopped Pi agent runtime.", stage="finalizing"))
            raise
        finally:
            cancel_task.cancel()
            session_completion_task.cancel()
            self._active_runs.pop(request_id, None)
            await run.wait_for_tools()
        if restart_sidecar_after_result:
            await self._terminate_sidecar()

        stats = result_payload.get("stats") if isinstance(result_payload.get("stats"), dict) else {}
        tokens = cast(dict[str, object], stats).get("tokens") if isinstance(stats, dict) else {}
        used_tokens = None
        if isinstance(tokens, dict) and isinstance(tokens.get("total"), int):
            used_tokens = int(tokens["total"])

        text = str(result_payload.get("text", "")).strip()
        if not text:
            session_file = Path(str(result_payload.get("session_file", "") or ""))
            session_error = _extract_session_error(session_file) if session_file else ""
            if session_error:
                raise RuntimeError(f"Pi provider error: {session_error}")

        return {
            "text": text,
            "used_tokens": used_tokens,
            "used_mcp_tools": run.used_tools,
            "system_trace_messages": run.system_trace_messages,
            "execution_events": run.execution_events,
        }

    async def _watch_session_completion(self, *, request: dict[str, object], run: PiActiveRun) -> None:
        data_dir = Path(str(request.get("pi_data_dir") or DATA_DIR / "pi_sessions"))
        session_dir = data_dir / "sessions"
        map_path = data_dir / "session-map.json"
        session_key = str(request.get("session_key", "") or "")
        message = str(request.get("message", "") or "")
        started_at = time.time()
        start_lines: dict[Path, int] = {}
        existing_session = _session_file_from_map(map_path, session_key)
        if existing_session is not None:
            start_lines[existing_session] = _count_jsonl_lines(existing_session)
        while not run.future.done() and not run.cancellation_token.is_cancelled:
            for session_file in _candidate_session_files(
                session_dir=session_dir,
                map_path=map_path,
                session_key=session_key,
                message=message,
                started_at=started_at,
            ):
                start_line = start_lines.setdefault(session_file, 0)
                completion = _extract_assistant_completion(session_file, after_line=start_line)
                if completion is None:
                    continue
                payload: dict[str, object] = {
                    "type": "result",
                    "request_id": run.request_id,
                    "text": completion["text"],
                    "session_file": str(session_file),
                    "stats": {"tokens": completion["tokens"]},
                    "_restart_sidecar": True,
                }
                if not run.future.done():
                    run.future.set_result(payload)
                return
            await asyncio.sleep(0.25)

    async def _terminate_sidecar(self) -> None:
        process = self._process
        if process is None or process.returncode is not None:
            return
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=3)
        except Exception:
            process.kill()
            await process.wait()
        if self._reader_task is not None:
            self._reader_task.cancel()
        self._process = None
        self._reader_task = None

    async def send(self, payload: dict[str, object]) -> None:
        process = self._process
        if process is None or process.stdin is None or process.returncode is not None:
            raise RuntimeError("Pi sidecar is not running.")
        encoded = (json.dumps(payload, ensure_ascii=True) + "\n").encode("utf-8")
        async with self._write_lock:
            process.stdin.write(encoded)
            await process.stdin.drain()

    async def _health_check(self) -> None:
        health_id = f"health-{uuid.uuid4().hex}"
        future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._pending_health[health_id] = future
        await self.send({"type": "health", "request_id": health_id})
        try:
            await asyncio.wait_for(future, timeout=30)
        finally:
            self._pending_health.pop(health_id, None)

    async def _reader_loop(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        try:
            while True:
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
                await self._handle_payload(cast(dict[str, object], payload))
        finally:
            await self._handle_process_exit()

    async def _handle_payload(self, payload: dict[str, object]) -> None:
        request_id = str(payload.get("request_id", "")).strip()
        payload_type = str(payload.get("type", "")).strip()
        if payload_type == "ready":
            future = self._pending_health.get(request_id)
            if future is not None and not future.done():
                future.set_result(None)
            return
        if payload_type == "error" and request_id in self._pending_health:
            future = self._pending_health.get(request_id)
            if future is not None and not future.done():
                future.set_exception(RuntimeError(str(payload.get("error", "") or "Pi sidecar health check failed.")))
            return

        active = self._active_runs.get(request_id)
        if active is None:
            logger.debug("Ignoring Pi payload for unknown request_id=%s type=%s", request_id, payload_type)
            return
        if payload_type == "event":
            await active.handle_pi_event(payload.get("event"))
            return
        if payload_type == "tool_call":
            active.handle_tool_call(payload)
            return
        if payload_type == "result":
            if not active.future.done():
                active.future.set_result(payload)
            return
        if payload_type == "error":
            if not active.future.done():
                active.future.set_exception(RuntimeError(str(payload.get("error", "") or "Pi sidecar failed.")))
            return
        if payload_type == "cancelled":
            if not active.future.done():
                active.future.set_exception(asyncio.CancelledError("Pi run cancelled."))

    async def _handle_process_exit(self) -> None:
        stderr_text = ""
        process = self._process
        if process is not None and process.stderr is not None:
            try:
                raw_stderr = await process.stderr.read()
                stderr_text = raw_stderr.decode("utf-8", errors="replace").strip()
            except Exception:
                stderr_text = ""
        detail = stderr_text or "Pi sidecar exited unexpectedly."
        self._last_start_error = detail
        for future in self._pending_health.values():
            if not future.done():
                future.set_exception(RuntimeError(detail))
        for active in self._active_runs.values():
            if not active.future.done():
                active.future.set_exception(RuntimeError(detail))
        self._pending_health.clear()
        self._active_runs.clear()


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
    history: list[dict[str, str]],
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
        "history": _normalize_history_for_pi(history),
        "provider": provider,
        "krill_tools": [_serialize_tool_entry(entry) for entry in tool_entries],
    }


def _session_file_from_map(map_path: Path, session_key: str) -> Path | None:
    if not session_key or not map_path.exists():
        return None
    try:
        raw_map = json.loads(map_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(raw_map, dict):
        return None
    raw_path = raw_map.get(session_key)
    if not isinstance(raw_path, str) or not raw_path.strip():
        return None
    session_file = Path(raw_path)
    return session_file if session_file.exists() else None


def _count_jsonl_lines(session_file: Path) -> int:
    try:
        return len([line for line in session_file.read_text(encoding="utf-8").splitlines() if line.strip()])
    except Exception:
        return 0


def _content_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    chunks: list[str] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        text = part.get("text")
        if isinstance(text, str):
            chunks.append(text)
    return "".join(chunks).strip()


def _session_contains_user_message(session_file: Path, message: str) -> bool:
    if not message:
        return False
    try:
        lines = [line for line in session_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    except Exception:
        return False
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        raw_message = entry.get("message") if isinstance(entry, dict) and entry.get("type") == "message" else entry
        if not isinstance(raw_message, dict) or raw_message.get("role") != "user":
            continue
        if _content_text(raw_message.get("content")) == message:
            return True
    return False


def _candidate_session_files(
    *,
    session_dir: Path,
    map_path: Path,
    session_key: str,
    message: str,
    started_at: float,
) -> list[Path]:
    candidates: list[Path] = []
    mapped = _session_file_from_map(map_path, session_key)
    if mapped is not None:
        candidates.append(mapped)
    try:
        recent_files = sorted(
            session_dir.glob("*.jsonl"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
    except Exception:
        recent_files = []
    for session_file in recent_files:
        try:
            if session_file.stat().st_mtime < started_at - 1:
                continue
        except Exception:
            continue
        if _session_contains_user_message(session_file, message):
            candidates.append(session_file)
    deduped: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate.resolve()) if candidate.exists() else str(candidate)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped


def _extract_assistant_completion(session_file: Path, *, after_line: int) -> dict[str, object] | None:
    try:
        lines = [line for line in session_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    except Exception:
        return None
    for index in range(len(lines) - 1, max(after_line, 0) - 1, -1):
        try:
            entry = json.loads(lines[index])
        except json.JSONDecodeError:
            continue
        raw_message = entry.get("message") if isinstance(entry, dict) and entry.get("type") == "message" else entry
        if not isinstance(raw_message, dict) or raw_message.get("role") != "assistant":
            continue
        text = _content_text(raw_message.get("content"))
        if not text:
            continue
        usage = raw_message.get("usage") if isinstance(raw_message.get("usage"), dict) else {}
        tokens = {
            "input": int(usage.get("input", usage.get("inputTokens", 0)) or 0),
            "output": int(usage.get("output", usage.get("outputTokens", 0)) or 0),
            "cacheRead": int(usage.get("cacheRead", usage.get("cacheReadTokens", 0)) or 0),
            "cacheWrite": int(usage.get("cacheWrite", usage.get("cacheWriteTokens", 0)) or 0),
            "total": int(usage.get("totalTokens", usage.get("total", 0)) or 0),
        }
        if tokens["total"] <= 0:
            tokens["total"] = tokens["input"] + tokens["output"] + tokens["cacheRead"] + tokens["cacheWrite"]
        return {"text": text, "tokens": tokens}
    return None


def _extract_session_error(session_file: Path) -> str:
    if not session_file.exists():
        return ""
    try:
        lines = [line for line in session_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    except Exception:
        return ""
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        raw_message = entry.get("message") if isinstance(entry, dict) and entry.get("type") == "message" else entry
        if not isinstance(raw_message, dict) or raw_message.get("role") != "assistant":
            continue
        error_message = raw_message.get("errorMessage")
        if isinstance(error_message, str) and error_message.strip():
            return error_message.strip()
    return ""


def _normalize_history_for_pi(history: list[dict[str, str]]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for turn in history:
        if not isinstance(turn, dict):
            continue
        role = str(turn.get("role", "")).strip().lower()
        content = str(turn.get("content", "")).strip()
        if role not in {"system", "user", "assistant"} or not content:
            continue
        normalized.append({"role": role, "content": content})
    return normalized


def _serialize_tool_entry(entry: PiToolEntry) -> dict[str, object]:
    return {
        "mcp_id": entry["mcp_id"],
        "mcp_label": entry["mcp_label"],
        "tool_id": entry["tool_id"],
        "tool_label": entry["tool_label"],
        "tool_description": entry["tool_description"],
        "input_schema": entry["input_schema"],
    }


async def _start_sidecar_process(provider: PiProviderConfig | None = None) -> asyncio.subprocess.Process:
    command = os.getenv("KRILL_PI_SIDECAR_COMMAND", "").strip()
    if command:
        args = shlex.split(command)
    else:
        args = [_node_executable(), str(_SIDE_CAR_ENTRYPOINT)]
    env = os.environ.copy()
    if provider is not None:
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
        return None
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
