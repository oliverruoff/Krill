"""OpenCode MCP plugin for delegating coding tasks via `npx opencode run`."""

import asyncio
import contextlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from app.config import BASE_DIR, Settings, load_settings
from app.tooling.runtime_context import get_runtime_context

from .base import MCPPlugin, McpConfigField, McpToolSpec
from .git_ops import SSH_PRIVATE_PARAM, ensure_ssh_keypair, get_workspace_path


class OpenCodeMCP(MCPPlugin):
    mcp_id = "opencode"
    display_name = "OpenCode"
    description = "Runs the OpenCode coding agent via CLI for planning and implementation tasks."
    default_enabled = False
    _ZEN_FREE_MODEL = "opencode/minimax-m2.5-free"
    config_fields: list[McpConfigField] = [
        McpConfigField(
            id="zen_api_key",
            label="OpenCode Zen API Key",
            type="password",
            required=True,
            description="API key for OpenCode Zen. OpenCode MCP always uses the free model opencode/minimax-m2.5-free.",
        )
    ]

    def __init__(self) -> None:
        self._session_by_chat: dict[tuple[str, str], str] = {}
        self._health_ok_until: float = 0.0
        self._last_health_error: str = ""

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
        npx_bin = shutil.which("npx")
        if not npx_bin:
            return False, "npx is not available. Install Node.js/npm in the runtime container first."

        try:
            await self._ensure_opencode_available(force=True)
        except Exception as exc:
            return False, str(exc)

        api_key = _extract_zen_api_key(params)
        if not api_key:
            return False, "OpenCode Zen API key is required."

        return True, f"OpenCode MCP is ready with fixed free model {self._ZEN_FREE_MODEL}."

    async def call_tool(self, tool_id: str, arguments: dict[str, object], params: dict[str, str]) -> dict[str, object]:
        if tool_id not in {"opencode_plan", "opencode_build"}:
            raise RuntimeError(f"Unsupported OpenCode tool: {tool_id}")

        runtime_context = get_runtime_context()
        source_channel = str(runtime_context.get("source_channel", "gateway") or "gateway")
        source_chat_id = str(runtime_context.get("source_chat_id", "") or "")

        prompt = _required_str(arguments, "prompt")
        repo_id = _optional_str(arguments, "repo_id")
        workdir_arg = _optional_str(arguments, "workdir")
        new_session = _optional_bool(arguments, "new_session", False)
        timeout_seconds = _optional_int(arguments, "timeout_seconds", 300, 10, 1200)

        settings = await load_settings()
        await self._ensure_opencode_available(force=False)
        api_key = _extract_zen_api_key(params)
        if not api_key:
            raise RuntimeError("OpenCode Zen API key is missing in OpenCode MCP configuration.")
        command = ["npx", "-y", "opencode-ai", "run", "--format", "json", "--model", self._ZEN_FREE_MODEL]

        session_key = (source_channel, source_chat_id)
        previous_session_id = _normalize_session_id(self._session_by_chat.get(session_key, ""))
        if not previous_session_id and session_key in self._session_by_chat:
            self._session_by_chat.pop(session_key, None)
        if previous_session_id and not new_session:
            command.extend(["--session", previous_session_id])

        mode_instruction = _mode_instruction(tool_id)
        command.append(f"{mode_instruction}\n\nUser request:\n{prompt}")

        workdir, workdir_note = _resolve_workdir(repo_id=repo_id, workdir_arg=workdir_arg)
        env = _build_opencode_env(zen_api_key=api_key)
        env = await _add_git_ssh_env(env=env, settings=settings)

        result = await _run_opencode(command=command, workdir=workdir, env=env, timeout_seconds=timeout_seconds)

        parsed = _parse_opencode_output(result["stdout"])

        session_id = _normalize_session_id(parsed.get("session_id", ""))
        if session_id:
            self._session_by_chat[session_key] = session_id
        elif previous_session_id and not new_session:
            session_id = previous_session_id

        response: dict[str, object] = {
            "status": "needs_user_input" if parsed.get("needs_user_input") else "ok",
            "text": parsed.get("text", ""),
            "question": parsed.get("question", ""),
            "session_id": session_id,
            "provider_id": "opencode",
            "model": self._ZEN_FREE_MODEL,
            "workdir": str(workdir),
        }
        if workdir_note:
            response["workdir_note"] = workdir_note
        stderr_text = str(result.get("stderr", "") or "").strip()
        if stderr_text:
            response["stderr"] = stderr_text

        text_value = str(response.get("text", "") or "").strip()
        question_value = str(response.get("question", "") or "").strip()
        if not text_value and not question_value and stderr_text:
            response["status"] = "error"
            if "ProviderModelNotFoundError" in stderr_text:
                response["error"] = "Selected provider/model is not available in OpenCode."
            elif "sessionID" in stderr_text and "ZodError" in stderr_text:
                response["error"] = "OpenCode session id was invalid; started without session continuation."
        return response

    async def _ensure_opencode_available(self, *, force: bool) -> None:
        now = time.monotonic()
        if not force and not self._last_health_error and now < self._health_ok_until:
            return
        if not force and self._last_health_error and now < self._health_ok_until:
            raise RuntimeError(self._last_health_error)

        try:
            await asyncio.to_thread(_verify_opencode_cli)
        except Exception as exc:
            self._health_ok_until = time.monotonic() + 30.0
            self._last_health_error = f"OpenCode CLI is unavailable: {exc}"
            raise RuntimeError(self._last_health_error) from exc

        self._last_health_error = ""
        self._health_ok_until = time.monotonic() + 600.0


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


def _normalize_session_id(value: object) -> str:
    if not isinstance(value, str):
        return ""
    session_id = value.strip()
    if not session_id.startswith("ses"):
        return ""
    return session_id


def _extract_zen_api_key(params: dict[str, str]) -> str:
    return str(params.get("zen_api_key", "") or "").strip()


def _build_opencode_env(*, zen_api_key: str) -> dict[str, str]:
    env = dict(os.environ)
    env["OPENCODE_API_KEY"] = zen_api_key

    return env


def _resolve_workdir(*, repo_id: str, workdir_arg: str) -> tuple[Path, str]:
    workspace = get_workspace_path()
    workspace.mkdir(parents=True, exist_ok=True)
    base_dir = BASE_DIR.resolve()

    note = ""
    if repo_id:
        candidate = (workspace / repo_id).resolve()
    elif workdir_arg:
        raw = Path(workdir_arg)
        candidate = raw.resolve() if raw.is_absolute() else (workspace / raw).resolve()
    else:
        candidate = workspace

    if candidate != workspace and workspace not in candidate.parents:
        if candidate == base_dir or base_dir in candidate.parents:
            candidate = workspace
            note = "Requested workdir was outside workspace and was auto-adjusted to workspace root."
        else:
            candidate = workspace
            note = "Requested workdir was invalid and was auto-adjusted to workspace root."
    if not candidate.exists() or not candidate.is_dir():
        raise RuntimeError(f"OpenCode workdir does not exist: {candidate}")
    return candidate, note


def _verify_opencode_cli() -> None:
    completed = subprocess.run(
        ["npx", "-y", "opencode-ai", "--version"],
        capture_output=True,
        text=True,
        timeout=25,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or "").strip() or (completed.stdout or "").strip() or "unknown error"
        raise RuntimeError(detail)


async def _add_git_ssh_env(*, env: dict[str, str], settings: Settings) -> dict[str, str]:
    updated = dict(env)
    workspace = get_workspace_path()
    workspace.mkdir(parents=True, exist_ok=True)

    git_config = settings.mcp_configs.get("git_ops")
    git_params = dict(git_config.params) if git_config is not None else {}
    private_key = str(git_params.get(SSH_PRIVATE_PARAM, "") or "").strip()
    if private_key:
        await ensure_ssh_keypair(git_params, workspace)
        key_path = workspace / ".ssh" / "krill_ed25519"
        updated["GIT_SSH_COMMAND"] = (
            f"ssh -i {key_path} -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"
        )
    return updated


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
