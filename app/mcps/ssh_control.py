"""SSH Control MCP plugin for chat-driven remote command execution."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import socket
import time
from dataclasses import dataclass
from typing import Any

from app.tooling.runtime_context import get_runtime_context

from .base import MCPPlugin, McpConfigField, McpToolSpec


try:
    import paramiko
except Exception as exc:  # pragma: no cover - dependency may be missing in some environments
    paramiko = None
    _PARAMIKO_IMPORT_ERROR = str(exc)
else:
    _PARAMIKO_IMPORT_ERROR = ""


@dataclass
class _SSHSession:
    client: Any
    host: str
    port: int
    username: str
    auth_method: str
    connected_at: float
    fingerprint_sha256: str
    lock: asyncio.Lock


class SSHControlMCP(MCPPlugin):
    mcp_id = "ssh_control"
    display_name = "SSH Control"
    description = "Connects to SSH hosts and executes remote shell commands."
    default_enabled = False
    config_fields: list[McpConfigField] = []

    def __init__(self) -> None:
        self._sessions: dict[tuple[str, str], _SSHSession] = {}
        self._sessions_lock = asyncio.Lock()

    def tool_specs(self) -> list[McpToolSpec]:
        return [
            McpToolSpec(
                id="ssh_connect",
                label="SSH Connect",
                description=(
                    "Connects to an SSH server using password or private key auth. "
                    "Default host-key behavior accepts any host key."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "host": {"type": "string", "minLength": 1},
                        "port": {"type": "integer", "minimum": 1, "maximum": 65535},
                        "username": {"type": "string", "minLength": 1},
                        "password": {"type": "string"},
                        "private_key": {"type": "string"},
                        "private_key_passphrase": {"type": "string"},
                        "strict_host_key_checking": {"type": "boolean"},
                        "connect_timeout_seconds": {"type": "integer", "minimum": 3, "maximum": 120},
                        "new_session": {"type": "boolean"},
                        "nonce": {"type": "string"},
                    },
                    "required": ["host", "username"],
                },
            ),
            McpToolSpec(
                id="ssh_execute",
                label="SSH Execute",
                description="Executes one command on the active SSH session and returns stdout/stderr/exit code.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "minLength": 1},
                        "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 600},
                        "max_output_chars": {"type": "integer", "minimum": 1000, "maximum": 200000},
                        "nonce": {"type": "string"},
                    },
                    "required": ["command"],
                },
            ),
            McpToolSpec(
                id="ssh_connection_info",
                label="SSH Connection Info",
                description="Returns metadata about the current SSH connection for this chat context.",
                input_schema={"type": "object", "properties": {"nonce": {"type": "string"}}},
            ),
            McpToolSpec(
                id="ssh_disconnect",
                label="SSH Disconnect",
                description="Closes the active SSH session for this chat context.",
                input_schema={"type": "object", "properties": {"nonce": {"type": "string"}}},
            ),
        ]

    def tool_call_system_reminder(self, tool_id: str, params: dict[str, str]) -> str:
        del params
        if tool_id == "ssh_connect":
            return (
                "SSH safety reminder:\n"
                "- Do not disclose passwords or private keys in assistant output.\n"
                "- Connect only to the host explicitly requested by the user.\n"
                "- Return JSON only with this shape: {\"arguments\":{...}}"
            )
        return (
            "SSH execution reminder:\n"
            "- Execute only commands required to complete the user's request.\n"
            "- Prefer read-only inspection unless user requested state changes.\n"
            "- Return JSON only with this shape: {\"arguments\":{...}}"
        )

    async def verify(self, params: dict[str, str]) -> tuple[bool, str]:
        del params
        if paramiko is None:
            return False, f"Paramiko is not available: {_PARAMIKO_IMPORT_ERROR or 'import failed'}"
        return True, "SSH Control MCP is ready."

    async def call_tool(self, tool_id: str, arguments: dict[str, object], params: dict[str, str]) -> dict[str, object]:
        del params
        if paramiko is None:
            raise RuntimeError(f"Paramiko is not available: {_PARAMIKO_IMPORT_ERROR or 'import failed'}")

        if tool_id == "ssh_connect":
            return await self._connect(arguments)
        if tool_id == "ssh_execute":
            return await self._execute(arguments)
        if tool_id == "ssh_connection_info":
            return await self._connection_info()
        if tool_id == "ssh_disconnect":
            return await self._disconnect()
        raise RuntimeError(f"Unsupported SSH Control tool: {tool_id}")

    async def _connect(self, arguments: dict[str, object]) -> dict[str, object]:
        host = _required_str(arguments, "host")
        username = _required_str(arguments, "username")
        port = _optional_int(arguments, "port", 22, 1, 65535)
        password = _optional_str(arguments, "password")
        private_key = _optional_str(arguments, "private_key")
        private_key_passphrase = _optional_str(arguments, "private_key_passphrase")
        strict_host_key_checking = _optional_bool(arguments, "strict_host_key_checking", False)
        connect_timeout_seconds = _optional_int(arguments, "connect_timeout_seconds", 10, 3, 120)
        new_session = _optional_bool(arguments, "new_session", False)

        auth_method = ""
        if private_key:
            auth_method = "private_key"
        elif password:
            auth_method = "password"
        else:
            raise RuntimeError("ssh_connect requires either 'password' or 'private_key'.")

        key = self._runtime_key()
        existing = await self._get_session(key)
        if existing is not None and not new_session:
            return {
                "ok": True,
                "action": "ssh_connect",
                "reused": True,
                "host": existing.host,
                "port": existing.port,
                "username": existing.username,
                "auth_method": existing.auth_method,
                "fingerprint_sha256": existing.fingerprint_sha256,
                "connected_for_seconds": max(0, int(time.time() - existing.connected_at)),
            }

        client = paramiko.SSHClient()
        if strict_host_key_checking:
            client.set_missing_host_key_policy(paramiko.RejectPolicy())
            client.load_system_host_keys()
        else:
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        pkey = _load_private_key(private_key, private_key_passphrase) if private_key else None

        try:
            await asyncio.to_thread(
                client.connect,
                hostname=host,
                port=port,
                username=username,
                password=password or None,
                pkey=pkey,
                look_for_keys=False,
                allow_agent=False,
                timeout=connect_timeout_seconds,
                banner_timeout=connect_timeout_seconds,
                auth_timeout=connect_timeout_seconds,
            )
        except Exception as exc:
            with _suppress_exceptions():
                await asyncio.to_thread(client.close)
            raise RuntimeError(f"SSH connect failed: {exc}") from exc

        transport = client.get_transport()
        if transport is None or not transport.is_active():
            with _suppress_exceptions():
                await asyncio.to_thread(client.close)
            raise RuntimeError("SSH connection failed: transport is not active.")

        server_key = transport.get_remote_server_key()
        fingerprint_sha256 = _host_key_fingerprint_sha256(server_key)

        new_value = _SSHSession(
            client=client,
            host=host,
            port=port,
            username=username,
            auth_method=auth_method,
            connected_at=time.time(),
            fingerprint_sha256=fingerprint_sha256,
            lock=asyncio.Lock(),
        )

        old_value = await self._set_session(key, new_value)
        if old_value is not None:
            with _suppress_exceptions():
                await asyncio.to_thread(old_value.client.close)

        return {
            "ok": True,
            "action": "ssh_connect",
            "reused": False,
            "host": host,
            "port": port,
            "username": username,
            "auth_method": auth_method,
            "strict_host_key_checking": strict_host_key_checking,
            "fingerprint_sha256": fingerprint_sha256,
        }

    async def _execute(self, arguments: dict[str, object]) -> dict[str, object]:
        session = await self._require_session()
        command = _required_str(arguments, "command")
        timeout_seconds = _optional_int(arguments, "timeout_seconds", 60, 1, 600)
        max_output_chars = _optional_int(arguments, "max_output_chars", 20000, 1000, 200000)

        async with session.lock:
            try:
                result = await asyncio.to_thread(
                    _run_ssh_command,
                    session.client,
                    command,
                    timeout_seconds,
                    max_output_chars,
                )
            except TimeoutError as exc:
                return {
                    "ok": False,
                    "action": "ssh_execute",
                    "timed_out": True,
                    "timeout_seconds": timeout_seconds,
                    "error": "command_timeout",
                    "detail": str(exc),
                }
            except Exception as exc:
                raise RuntimeError(f"SSH command failed: {exc}") from exc

        return {
            "ok": True,
            "action": "ssh_execute",
            "timed_out": False,
            "command": command,
            "exit_code": result["exit_code"],
            "stdout": result["stdout"],
            "stderr": result["stderr"],
            "truncated": result["truncated"],
            "duration_ms": result["duration_ms"],
        }

    async def _connection_info(self) -> dict[str, object]:
        key = self._runtime_key()
        session = await self._get_session(key)
        if session is None:
            return {
                "ok": True,
                "action": "ssh_connection_info",
                "connected": False,
            }

        connected = await asyncio.to_thread(_is_client_connected, session.client)
        return {
            "ok": True,
            "action": "ssh_connection_info",
            "connected": bool(connected),
            "host": session.host,
            "port": session.port,
            "username": session.username,
            "auth_method": session.auth_method,
            "fingerprint_sha256": session.fingerprint_sha256,
            "connected_for_seconds": max(0, int(time.time() - session.connected_at)),
        }

    async def _disconnect(self) -> dict[str, object]:
        key = self._runtime_key()
        async with self._sessions_lock:
            session = self._sessions.pop(key, None)
        if session is None:
            return {
                "ok": True,
                "action": "ssh_disconnect",
                "disconnected": False,
                "reason": "no_active_session",
            }

        with _suppress_exceptions():
            await asyncio.to_thread(session.client.close)
        return {
            "ok": True,
            "action": "ssh_disconnect",
            "disconnected": True,
            "host": session.host,
            "port": session.port,
            "username": session.username,
        }

    async def _require_session(self) -> _SSHSession:
        key = self._runtime_key()
        session = await self._get_session(key)
        if session is None:
            raise RuntimeError("No active SSH session. Run ssh_connect first.")
        connected = await asyncio.to_thread(_is_client_connected, session.client)
        if not connected:
            raise RuntimeError("SSH session is not connected. Reconnect with ssh_connect.")
        return session

    async def _get_session(self, key: tuple[str, str]) -> _SSHSession | None:
        async with self._sessions_lock:
            return self._sessions.get(key)

    async def _set_session(self, key: tuple[str, str], value: _SSHSession) -> _SSHSession | None:
        async with self._sessions_lock:
            previous = self._sessions.get(key)
            self._sessions[key] = value
            return previous

    def _runtime_key(self) -> tuple[str, str]:
        context = get_runtime_context()
        source_channel = _safe_string(context.get("source_channel", "gateway")) or "gateway"
        source_chat_id = _safe_string(context.get("source_chat_id", ""))
        return source_channel, source_chat_id


def _run_ssh_command(client: Any, command: str, timeout_seconds: int, max_output_chars: int) -> dict[str, object]:
    started = time.time()
    stdin, stdout, stderr = client.exec_command(command, timeout=timeout_seconds, get_pty=False)
    with _suppress_exceptions():
        stdin.close()

    stdout.channel.settimeout(timeout_seconds)
    stderr.channel.settimeout(timeout_seconds)
    try:
        stdout_bytes = stdout.read()
        stderr_bytes = stderr.read()
        exit_code = stdout.channel.recv_exit_status()
    except socket.timeout as exc:
        raise TimeoutError(f"Command exceeded timeout of {timeout_seconds}s.") from exc

    stdout_text = _decode_output(stdout_bytes)
    stderr_text = _decode_output(stderr_bytes)
    combined_len = len(stdout_text) + len(stderr_text)
    truncated = combined_len > max_output_chars
    if truncated:
        budget_stdout = max_output_chars // 2
        budget_stderr = max_output_chars - budget_stdout
        stdout_text = _truncate(stdout_text, budget_stdout)
        stderr_text = _truncate(stderr_text, budget_stderr)

    return {
        "exit_code": int(exit_code),
        "stdout": stdout_text,
        "stderr": stderr_text,
        "truncated": truncated,
        "duration_ms": int((time.time() - started) * 1000),
    }


def _load_private_key(private_key_text: str, passphrase: str) -> Any:
    key_text = private_key_text.strip()
    if not key_text:
        return None

    password = passphrase if passphrase else None
    key_loaders = [
        paramiko.RSAKey.from_private_key,
        paramiko.ECDSAKey.from_private_key,
        paramiko.Ed25519Key.from_private_key,
        paramiko.DSSKey.from_private_key,
    ]
    last_error = "Unsupported private key format."
    for loader in key_loaders:
        key_stream = io.StringIO(key_text)
        try:
            return loader(key_stream, password=password)
        except Exception as exc:
            last_error = str(exc)
    raise RuntimeError(f"Failed to parse private key: {last_error}")


def _host_key_fingerprint_sha256(server_key: Any) -> str:
    key_bytes = server_key.asbytes()
    digest = hashlib.sha256(key_bytes).digest()
    encoded = base64.b64encode(digest).decode("ascii").rstrip("=")
    return f"SHA256:{encoded}"


def _is_client_connected(client: Any) -> bool:
    transport = client.get_transport()
    return bool(transport is not None and transport.is_active())


def _decode_output(raw: object) -> str:
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    if isinstance(raw, str):
        return raw
    return _safe_string(raw)


def _truncate(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[:max_chars] + "\n...[truncated]"


def _required_str(arguments: dict[str, object], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"Missing required argument '{key}'.")
    return value.strip()


def _optional_str(arguments: dict[str, object], key: str) -> str:
    value = arguments.get(key)
    if isinstance(value, str):
        return value
    return ""


def _optional_int(arguments: dict[str, object], key: str, default: int, min_value: int, max_value: int) -> int:
    value = arguments.get(key)
    if not isinstance(value, int):
        return default
    return max(min_value, min(max_value, value))


def _optional_bool(arguments: dict[str, object], key: str, default: bool) -> bool:
    value = arguments.get(key)
    if isinstance(value, bool):
        return value
    return default


def _safe_string(value: object) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return str(value)


class _suppress_exceptions:
    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        del exc_type, exc, tb
        return True
