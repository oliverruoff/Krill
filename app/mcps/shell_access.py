"""Shell Access MCP plugin for generic shell command execution and file sharing."""

import asyncio
import subprocess
from pathlib import Path

from app.config import BASE_DIR
from app.shared_files import create_shared_file_link

from .base import MCPPlugin, McpConfigField, McpToolSpec


_SHARE_FILE_MAX_BYTES = 25 * 1024 * 1024
_PUBLIC_BASE_URL_PARAM = "public_base_url"


class ShellAccessMCP(MCPPlugin):
    mcp_id = "shell_access"
    display_name = "Shell Access"
    description = (
        "Executes any shell command on the host system and creates temporary signed download links for local files. "
        "Supports ssh, grep, sed, awk, python, bash scripts, scp, curl, and all other shell tools."
    )
    default_enabled = True
    config_fields: list[McpConfigField] = [
        McpConfigField(
            id=_PUBLIC_BASE_URL_PARAM,
            label="Public Base URL",
            type="text",
            required=False,
            placeholder="http://127.0.0.1:8055",
            description=(
                "Optional base URL used to build absolute file links, e.g. http://192.168.1.126:8055. "
                "If empty, share_file returns a relative /api/files/shared/... URL."
            ),
        ),
    ]

    def tool_specs(self) -> list[McpToolSpec]:
        return [
            McpToolSpec(
                id="execute_shell",
                label="Execute Shell",
                description=(
                    "Executes any shell command on the host system. "
                    "Supports all standard shell tools: ssh, grep, sed, awk, find, curl, python, bash scripts, scp, rsync, git, etc. "
                    "For multi-step SSH workflows use ssh -o ControlMaster=auto -o ControlPath=/tmp/ssh-%r@%h:%p -o ControlPersist=60s to reuse connections."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "minLength": 1,
                            "description": "The full shell command string to execute.",
                        },
                        "workdir": {
                            "type": "string",
                            "description": "Optional working directory. Defaults to the application base directory.",
                        },
                        "timeout_seconds": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 120,
                            "description": "Max execution time in seconds (1–120). Defaults to 30.",
                        },
                    },
                    "required": ["command"],
                },
            ),
            McpToolSpec(
                id="share_file",
                label="Share File",
                description=(
                    "Creates a temporary signed download link for an existing local file so users can download it."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "minLength": 1},
                        "download_name": {"type": "string"},
                        "ttl_seconds": {"type": "integer", "minimum": 60, "maximum": 86400},
                    },
                    "required": ["path"],
                },
            ),
        ]

    def tool_call_system_reminder(self, tool_id: str, params: dict[str, str]) -> str:
        del params
        if tool_id == "execute_shell":
            return (
                "Shell Access reminder:\n"
                "- Run any shell command: ssh, grep, sed, awk, python, bash scripts, curl, scp, git, etc.\n"
                "- For SSH sessions across multiple commands, use ControlMaster:\n"
                "  ssh -o ControlMaster=auto -o ControlPath=/tmp/ssh-%r@%h:%p -o ControlPersist=60s user@host 'command'\n"
                "- Follow explicit user intent only; require clear confirmation for destructive operations.\n"
                "- Return JSON only with this shape: {\"arguments\":{...}}"
            )
        if tool_id == "share_file":
            return (
                "After calling share_file, include the returned download_url in your response exactly as returned. "
                "Never invent or rewrite host/port for shared links. "
                "For Telegram, keep the URL present in output so the integration can send the file as a document."
            )
        return ""

    async def verify(self, params: dict[str, str]) -> tuple[bool, str]:
        return True, "Shell Access MCP is ready without setup."

    async def call_tool(self, tool_id: str, arguments: dict[str, object], params: dict[str, str]) -> dict[str, object]:
        if tool_id == "execute_shell":
            command = _required_str(arguments, "command")
            workdir_raw = _optional_str(arguments, "workdir", str(BASE_DIR))
            workdir = Path(workdir_raw).expanduser().resolve()
            timeout_seconds = _optional_int(arguments, "timeout_seconds", 30, 1, 120)
            result = await asyncio.to_thread(_execute_shell, command, workdir, timeout_seconds)
            return result

        if tool_id == "share_file":
            file_path = Path(_required_str(arguments, "path")).expanduser().resolve()
            if not file_path.is_file():
                raise RuntimeError(f"Path is not a file: {file_path}")
            file_size = int(file_path.stat().st_size)
            if file_size <= 0:
                raise RuntimeError("Cannot share an empty file.")
            if file_size > _SHARE_FILE_MAX_BYTES:
                raise RuntimeError(
                    f"File is too large to share ({file_size} bytes). Limit is {_SHARE_FILE_MAX_BYTES} bytes."
                )

            link_payload = await create_shared_file_link(
                file_path,
                download_name=_optional_str(arguments, "download_name", file_path.name),
                ttl_seconds=_optional_int(arguments, "ttl_seconds", 3600, 60, 86400),
            )
            return {
                "status": "ok",
                "path": str(file_path),
                **link_payload,
                "download_url_absolute": _build_absolute_download_url(str(link_payload.get("download_url", "")), params),
            }

        raise RuntimeError(f"Unsupported Shell Access tool: {tool_id}")


def _execute_shell(command: str, workdir: Path, timeout_seconds: int) -> dict[str, object]:
    if not workdir.exists():
        workdir.mkdir(parents=True, exist_ok=True)
    if not workdir.is_dir():
        raise RuntimeError(f"Workdir is not a directory: {workdir}")

    try:
        completed = subprocess.run(
            command,
            shell=True,
            cwd=str(workdir),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        stdout_text = _truncate_text(completed.stdout, 20000)
        stderr_text = _truncate_text(completed.stderr, 20000)
        return {
            "ok": completed.returncode == 0,
            "command": command,
            "workdir": str(workdir),
            "exit_code": completed.returncode,
            "stdout": stdout_text,
            "stderr": stderr_text,
            "timed_out": False,
        }
    except subprocess.TimeoutExpired as exc:
        stdout_text = _truncate_text(exc.stdout if isinstance(exc.stdout, str) else "", 20000)
        stderr_text = _truncate_text(exc.stderr if isinstance(exc.stderr, str) else "", 20000)
        return {
            "ok": False,
            "command": command,
            "workdir": str(workdir),
            "exit_code": None,
            "stdout": stdout_text,
            "stderr": stderr_text,
            "timed_out": True,
            "timeout_seconds": timeout_seconds,
        }


def _truncate_text(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "\n...[truncated]"


def _required_str(arguments: dict[str, object], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"Missing required argument '{key}'.")
    return value.strip()


def _optional_str(arguments: dict[str, object], key: str, default: str) -> str:
    value = arguments.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default


def _optional_int(arguments: dict[str, object], key: str, default: int, min_value: int, max_value: int) -> int:
    value = arguments.get(key)
    if isinstance(value, int):
        return max(min_value, min(max_value, value))
    return default


def _build_absolute_download_url(download_url: str, params: dict[str, str]) -> str:
    path = str(download_url or "").strip()
    if not path.startswith("/"):
        return ""

    base_url = str(params.get(_PUBLIC_BASE_URL_PARAM, "") or "").strip().rstrip("/")
    if not base_url:
        return ""
    if not (base_url.startswith("http://") or base_url.startswith("https://")):
        return ""
    return f"{base_url}{path}"
