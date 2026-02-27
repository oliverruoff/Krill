"""OpenCode MCP plugin for delegating coding tasks via `npx opencode run`."""

import asyncio
import contextlib
import json
import os
import shutil
from pathlib import Path

from app.config import Settings, load_settings
from app.tooling.runtime_context import get_runtime_context

from .base import MCPPlugin, McpConfigField, McpConfigFieldOption, McpToolSpec
from .git_ops import get_workspace_path


class OpenCodeMCP(MCPPlugin):
    mcp_id = "opencode"
    display_name = "OpenCode"
    description = "Runs the OpenCode coding agent via CLI for planning and implementation tasks."
    default_enabled = False
    config_fields: list[McpConfigField] = [
        McpConfigField(
            id="provider_id",
            label="Provider",
            type="select",
            required=False,
            description="LLM provider used by OpenCode. Leave empty to use Krill active provider.",
            options_source="providers",
        ),
        McpConfigField(
            id="model",
            label="Model",
            type="select",
            required=False,
            description="Model used by OpenCode. Leave empty to use selected provider default model.",
            options_source="provider_models",
        ),
        McpConfigField(
            id="allowed_channels",
            label="Answer Channels",
            type="multiselect",
            required=False,
            description="Channels allowed to receive OpenCode responses. Gateway is always enabled.",
            options=[
                McpConfigFieldOption(value="gateway", label="Gateway", disabled=True),
            ],
            options_source="integration_channels",
        )
    ]

    def __init__(self) -> None:
        self._session_by_chat: dict[tuple[str, str], str] = {}

    def tool_specs(self) -> list[McpToolSpec]:
        prompt_schema = {
            "prompt": {"type": "string", "minLength": 1},
            "repo_id": {"type": "string"},
            "workdir": {"type": "string"},
            "new_session": {"type": "boolean"},
            "timeout_seconds": {"type": "integer", "minimum": 10, "maximum": 1200},
        }
        return [
            McpToolSpec(
                id="opencode_plan",
                label="OpenCode Plan",
                description=(
                    "Use OpenCode for architecture/planning/analysis questions. "
                    "Prefer this when the user asks how to approach coding work."
                ),
                input_schema={
                    "type": "object",
                    "properties": prompt_schema,
                    "required": ["prompt"],
                },
            ),
            McpToolSpec(
                id="opencode_build",
                label="OpenCode Build",
                description=(
                    "Use OpenCode for actual coding and repository changes. "
                    "Prefer this when the user requests implementation work."
                ),
                input_schema={
                    "type": "object",
                    "properties": prompt_schema,
                    "required": ["prompt"],
                },
            ),
        ]

    def tool_call_system_reminder(self, tool_id: str, params: dict[str, str]) -> str:
        del tool_id, params
        return ""

    async def verify(self, params: dict[str, str]) -> tuple[bool, str]:
        allowed = _parse_allowed_channels(params)
        if "gateway" not in allowed:
            return False, "OpenCode MCP requires gateway as an allowed channel."

        npx_bin = shutil.which("npx")
        if not npx_bin:
            return False, "npx is not available. Install Node.js/npm in the runtime container first."

        settings = await load_settings()
        provider_id, model_id, _ = _resolve_selected_provider(settings, params)
        if not provider_id:
            return False, "Active provider is not configured."
        provider_config = settings.provider_configs.get(provider_id)
        if provider_config is None:
            return False, f"Provider '{provider_id}' is not configured in Krill."
        if not provider_config.api_key.strip():
            return False, f"API key for provider '{provider_id}' is missing."
        if not model_id.strip():
            return False, f"Model for provider '{provider_id}' is missing."

        return True, "OpenCode MCP is ready."

    async def call_tool(self, tool_id: str, arguments: dict[str, object], params: dict[str, str]) -> dict[str, object]:
        if tool_id not in {"opencode_plan", "opencode_build"}:
            raise RuntimeError(f"Unsupported OpenCode tool: {tool_id}")

        allowed_channels = _parse_allowed_channels(params)
        runtime_context = get_runtime_context()
        source_channel = str(runtime_context.get("source_channel", "gateway") or "gateway")
        source_chat_id = str(runtime_context.get("source_chat_id", "") or "")
        if source_channel not in allowed_channels:
            return {
                "status": "blocked",
                "reason": (
                    f"OpenCode is not enabled for channel '{source_channel}'. "
                    f"Allowed channels: {', '.join(sorted(allowed_channels))}"
                ),
                "source_channel": source_channel,
            }

        prompt = _required_str(arguments, "prompt")
        repo_id = _optional_str(arguments, "repo_id")
        workdir_arg = _optional_str(arguments, "workdir")
        new_session = _optional_bool(arguments, "new_session", False)
        timeout_seconds = _optional_int(arguments, "timeout_seconds", 300, 10, 1200)

        settings = await load_settings()
        provider_id, model_id, api_key = _resolve_selected_provider(settings, params)
        opencode_model = _map_opencode_model(provider_id, model_id)
        command = ["npx", "-y", "opencode", "run", "--format", "json", "--model", opencode_model]

        session_key = (source_channel, source_chat_id)
        previous_session_id = self._session_by_chat.get(session_key, "")
        if previous_session_id and not new_session:
            command.extend(["--session", previous_session_id])

        mode_instruction = _mode_instruction(tool_id)
        command.append(f"{mode_instruction}\n\nUser request:\n{prompt}")

        workdir = _resolve_workdir(repo_id=repo_id, workdir_arg=workdir_arg)
        env = _build_opencode_env(provider_id=provider_id, api_key=api_key)

        result = await _run_opencode(command=command, workdir=workdir, env=env, timeout_seconds=timeout_seconds)
        parsed = _parse_opencode_output(result["stdout"])

        session_id = parsed.get("session_id", "")
        if isinstance(session_id, str) and session_id.strip():
            self._session_by_chat[session_key] = session_id.strip()
        elif previous_session_id and not new_session:
            session_id = previous_session_id

        response: dict[str, object] = {
            "status": "needs_user_input" if parsed.get("needs_user_input") else "ok",
            "text": parsed.get("text", ""),
            "question": parsed.get("question", ""),
            "session_id": session_id,
            "provider_id": provider_id,
            "model": opencode_model,
            "workdir": str(workdir),
        }
        stderr_text = str(result.get("stderr", "") or "").strip()
        if stderr_text:
            response["stderr"] = stderr_text
        return response


def _parse_allowed_channels(params: dict[str, str]) -> set[str]:
    raw = str(params.get("allowed_channels", "") or "").strip()
    values: list[str] = []
    if raw:
        try:
            payload = json.loads(raw)
            if isinstance(payload, list):
                values = [str(item).strip() for item in payload if str(item).strip()]
        except Exception:
            values = [chunk.strip() for chunk in raw.split(",") if chunk.strip()]

    normalized = set(values)
    normalized.add("gateway")
    return normalized


def _required_str(arguments: dict[str, object], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"Missing required argument '{key}'.")
    return value.strip()


def _optional_str(arguments: dict[str, object], key: str) -> str:
    value = arguments.get(key)
    if isinstance(value, str):
        return value.strip()
    return ""


def _optional_bool(arguments: dict[str, object], key: str, default: bool) -> bool:
    value = arguments.get(key)
    if isinstance(value, bool):
        return value
    return default


def _optional_int(arguments: dict[str, object], key: str, default: int, min_value: int, max_value: int) -> int:
    value = arguments.get(key)
    if not isinstance(value, int):
        return default
    return max(min_value, min(max_value, value))


def _resolve_selected_provider(settings: Settings, params: dict[str, str]) -> tuple[str, str, str]:
    selected_provider = str(params.get("provider_id", "") or "").strip()
    selected_model = str(params.get("model", "") or "").strip()

    provider_from_model = ""
    model_from_model = ""
    if "/" in selected_model:
        provider_from_model, model_from_model = selected_model.split("/", 1)
        provider_from_model = provider_from_model.strip().lower()
        model_from_model = model_from_model.strip()

    if selected_provider and provider_from_model and selected_provider.strip().lower() != provider_from_model:
        raise RuntimeError("OpenCode provider/model mismatch in MCP config.")

    provider_id = provider_from_model or selected_provider.strip().lower() or str(settings.active_provider_id or "").strip()
    if not provider_id:
        raise RuntimeError("Active provider is not configured.")

    provider_config = settings.provider_configs.get(provider_id)
    if provider_config is None:
        raise RuntimeError(f"Provider '{provider_id}' is not configured in Krill.")

    model_id = model_from_model or selected_model or str(provider_config.model or "").strip()
    api_key = str(provider_config.api_key or "").strip()
    if not model_id:
        raise RuntimeError(f"Provider '{provider_id}' model is missing.")
    if not api_key:
        raise RuntimeError(f"Provider '{provider_id}' API key is missing.")
    return provider_id, model_id, api_key


def _map_opencode_model(provider_id: str, model_id: str) -> str:
    model = model_id.strip()
    provider = provider_id.strip().lower()
    if provider == "openrouter":
        if model.lower() == "free":
            return "openrouter/free"
        if model.startswith("openrouter/"):
            return model
        return f"openrouter/{model}"
    if provider == "openai":
        if model.startswith("openai/"):
            return model
        return f"openai/{model}"
    if provider == "gemini":
        if model.startswith("gemini/"):
            return model
        return f"gemini/{model}"
    raise RuntimeError(f"OpenCode MCP does not support provider '{provider_id}'.")


def _build_opencode_env(*, provider_id: str, api_key: str) -> dict[str, str]:
    env = dict(os.environ)
    env["OPENAI_API_KEY"] = ""
    env["OPENROUTER_API_KEY"] = ""
    env["GEMINI_API_KEY"] = ""
    env["GOOGLE_API_KEY"] = ""

    provider = provider_id.strip().lower()
    if provider == "openai":
        env["OPENAI_API_KEY"] = api_key
    elif provider == "openrouter":
        env["OPENROUTER_API_KEY"] = api_key
    elif provider == "gemini":
        env["GEMINI_API_KEY"] = api_key
        env["GOOGLE_API_KEY"] = api_key
    else:
        raise RuntimeError(f"Unsupported provider for OpenCode MCP: {provider_id}")

    return env


def _resolve_workdir(*, repo_id: str, workdir_arg: str) -> Path:
    workspace = get_workspace_path()
    workspace.mkdir(parents=True, exist_ok=True)

    if repo_id:
        candidate = (workspace / repo_id).resolve()
    elif workdir_arg:
        raw = Path(workdir_arg)
        candidate = raw.resolve() if raw.is_absolute() else (workspace / raw).resolve()
    else:
        candidate = workspace

    if candidate != workspace and workspace not in candidate.parents:
        raise RuntimeError("OpenCode workdir must stay inside Krill workspace.")
    if not candidate.exists() or not candidate.is_dir():
        raise RuntimeError(f"OpenCode workdir does not exist: {candidate}")
    return candidate


def _mode_instruction(tool_id: str) -> str:
    if tool_id == "opencode_plan":
        return (
            "Mode: planning. Analyze and propose a concrete implementation plan. "
            "Do not execute destructive steps unless explicitly requested. "
            "If details are missing, ask a direct clarification question."
        )
    return (
        "Mode: build. Implement the requested coding task. "
        "If constraints are missing or risky actions are needed, ask a direct clarification question first."
    )


async def _run_opencode(*, command: list[str], workdir: Path, env: dict[str, str], timeout_seconds: int) -> dict[str, str]:
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(workdir),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("npx command not found. Install Node.js/npm in the runtime container.") from exc

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
    except asyncio.TimeoutError as exc:
        process.kill()
        with contextlib.suppress(Exception):
            await process.communicate()
        raise RuntimeError(f"OpenCode run timed out after {timeout_seconds}s.") from exc

    stdout_text = (stdout_bytes or b"").decode("utf-8", errors="ignore")
    stderr_text = (stderr_bytes or b"").decode("utf-8", errors="ignore")
    if process.returncode != 0:
        detail = stderr_text.strip() or stdout_text.strip() or f"OpenCode exited with status {process.returncode}."
        raise RuntimeError(detail)

    return {
        "stdout": _truncate_text(stdout_text, 100000),
        "stderr": _truncate_text(stderr_text, 20000),
    }


def _parse_opencode_output(stdout_text: str) -> dict[str, object]:
    raw = str(stdout_text or "")
    events: list[dict[str, object]] = []
    for line in raw.splitlines():
        cleaned = line.strip()
        if not cleaned:
            continue
        try:
            payload = json.loads(cleaned)
        except Exception:
            continue
        if isinstance(payload, dict):
            events.append(payload)

    if not events:
        return {
            "text": raw.strip(),
            "session_id": "",
            "needs_user_input": False,
            "question": "",
        }

    text_chunks: list[str] = []
    session_id = ""
    question = ""
    needs_user_input = False

    for event in events:
        if not session_id:
            maybe_session = _find_first_string(event, {"session_id", "sessionId", "session"})
            if maybe_session:
                session_id = maybe_session

        event_type = str(event.get("type", "") or "").strip().lower()
        if event_type in {"question", "input_required", "ask_user", "clarification"}:
            needs_user_input = True
            if not question:
                question = _find_first_string(event, {"question", "text", "content", "message"})

        chunk = _find_first_string(event, {"text", "content", "message", "delta", "output"})
        if chunk:
            text_chunks.append(chunk)

    joined = "\n".join(part.strip() for part in text_chunks if part and part.strip()).strip()
    if needs_user_input and not question:
        question = joined

    return {
        "text": joined,
        "session_id": session_id,
        "needs_user_input": needs_user_input,
        "question": question.strip(),
    }


def _find_first_string(payload: object, candidate_keys: set[str]) -> str:
    if isinstance(payload, str) and payload.strip():
        return payload.strip()
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in candidate_keys and isinstance(value, str) and value.strip():
                return value.strip()
        for value in payload.values():
            nested = _find_first_string(value, candidate_keys)
            if nested:
                return nested
    if isinstance(payload, list):
        for item in payload:
            nested = _find_first_string(item, candidate_keys)
            if nested:
                return nested
    return ""


def _truncate_text(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "\n...[truncated]"
