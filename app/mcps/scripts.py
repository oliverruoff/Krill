"""Scripts MCP plugin for creating and executing metadata-driven Python scripts."""

import asyncio
import json
import os
import re
import sys
import tempfile
import time
from importlib import metadata as importlib_metadata
from pathlib import Path

from app.config import SCRIPTS_DIR, delete_script, get_script, list_scripts, rehydrate_script_files, upsert_script

from .base import MCPPlugin, McpConfigField, McpToolSpec


_TITLE_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_REQ_ITEM_PATTERN = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)(?:\s*(?P<specifier>(==|!=|>=|<=|>|<|~=)\s*[A-Za-z0-9*._+-]+))?$"
)


class ScriptsMCP(MCPPlugin):
    mcp_id = "scripts"
    display_name = "Scripts"
    description = "Creates Krill script files with embedded metadata comments and DB-backed persistence."
    default_enabled = False
    config_fields: list[McpConfigField] = []

    def tool_specs(self) -> list[McpToolSpec]:
        return [
            McpToolSpec(
                id="create_script",
                label="Create Script",
                description=(
                    "Creates or updates a Python script in data/scripts with required metadata comment rows "
                    "and stores the script definition in braindump.db."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "minLength": 1, "maxLength": 64},
                        "description": {"type": "string", "minLength": 1, "maxLength": 1024},
                        "instructions": {"type": "string", "minLength": 1, "maxLength": 5000},
                        "python_requirements": {"type": "string", "maxLength": 500},
                        "body": {"type": "string"},
                        "overwrite": {"type": "boolean"},
                    },
                    "required": ["title", "description", "instructions"],
                },
            ),
            McpToolSpec(
                id="list_scripts",
                label="List Scripts",
                description="Lists stored script titles and metadata.",
                input_schema={"type": "object", "properties": {}},
            ),
            McpToolSpec(
                id="edit_script",
                label="Edit Script",
                description="Edits an existing stored script by title.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "minLength": 1, "maxLength": 64},
                        "description": {"type": "string", "minLength": 1, "maxLength": 1024},
                        "instructions": {"type": "string", "minLength": 1, "maxLength": 5000},
                        "python_requirements": {"type": "string", "maxLength": 500},
                        "body": {"type": "string"},
                    },
                    "required": ["title"],
                },
            ),
            McpToolSpec(
                id="check_script_requirements",
                label="Check Script Requirements",
                description="Checks whether python_requirements are currently installed.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "minLength": 1, "maxLength": 64},
                    },
                    "required": ["title"],
                },
            ),
            McpToolSpec(
                id="install_script_requirements",
                label="Install Script Requirements",
                description="Installs python_requirements for a stored script using pip.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "minLength": 1, "maxLength": 64},
                        "only_missing": {"type": "boolean"},
                        "timeout_ms": {"type": "integer", "minimum": 1000, "maximum": 300000},
                    },
                    "required": ["title"],
                },
            ),
            McpToolSpec(
                id="execute_script",
                label="Execute Script",
                description="Auto-installs missing python requirements, then executes script by title.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "minLength": 1, "maxLength": 64},
                        "input_json": {"type": "object"},
                        "timeout_ms": {"type": "integer", "minimum": 1000, "maximum": 120000},
                    },
                    "required": ["title"],
                },
            ),
            McpToolSpec(
                id="remove_script",
                label="Remove Script",
                description="Deletes a stored script from braindump.db and removes its file from data/scripts.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "minLength": 1, "maxLength": 64},
                    },
                    "required": ["title"],
                },
            ),
        ]

    async def verify(self, params: dict[str, str]) -> tuple[bool, str]:
        del params
        await asyncio.to_thread(SCRIPTS_DIR.mkdir, parents=True, exist_ok=True)
        return True, f"Scripts MCP is ready. Script root: {SCRIPTS_DIR}"

    def tool_call_system_reminder(self, tool_id: str, params: dict[str, str]) -> str:
        del params
        if tool_id not in {
            "create_script",
            "list_scripts",
            "edit_script",
            "check_script_requirements",
            "install_script_requirements",
            "execute_script",
            "remove_script",
        }:
            return ""
        return (
            "Scripts MCP reminder:\n"
            "- title must be lowercase letters/numbers/hyphens only and 1-64 chars.\n"
            "- python_requirements must be comma-separated pip requirement items.\n"
            "- execute_script auto-installs missing python requirements before running."
        )

    async def call_tool(self, tool_id: str, arguments: dict[str, object], params: dict[str, str]) -> dict[str, object]:
        del params
        if tool_id == "create_script":
            return await _create_script(arguments)
        if tool_id == "list_scripts":
            return await _list_scripts_tool()
        if tool_id == "edit_script":
            return await _edit_script(arguments)
        if tool_id == "check_script_requirements":
            return await _check_script_requirements_tool(arguments)
        if tool_id == "install_script_requirements":
            return await _install_script_requirements_tool(arguments)
        if tool_id == "execute_script":
            return await _execute_script(arguments)
        if tool_id == "remove_script":
            return await _remove_script(arguments)
        raise RuntimeError(f"Unsupported Scripts tool: {tool_id}")


async def _create_script(arguments: dict[str, object]) -> dict[str, object]:
    title = _required_script_title(arguments.get("title"))
    description = _required_limited_text(arguments.get("description"), "description", 1024)
    instructions = _required_limited_text(arguments.get("instructions"), "instructions", 5000)
    python_requirements = _optional_python_requirements(arguments)
    body = _optional_text(arguments.get("body"))
    overwrite = bool(arguments.get("overwrite", False))

    existing = await get_script(title)
    if existing is not None and not overwrite:
        raise RuntimeError("Script already exists. Set overwrite=true to update it.")

    file_name = f"{title}.py"
    saved = await upsert_script(
        {
            "id": title,
            "title": title,
            "description": description,
            "instructions": instructions,
            "python_requirements": python_requirements,
            "body": body,
            "file_name": file_name,
        },
        script_id=title,
    )
    rehydrate_stats = await rehydrate_script_files()
    return _script_payload(saved, "updated" if existing is not None else "created", rehydrate_stats)


async def _list_scripts_tool() -> dict[str, object]:
    scripts = await list_scripts()
    items: list[dict[str, str]] = []
    for script in scripts:
        file_name = str(script.file_name or "").strip()
        if not file_name:
            continue
        path = _resolve_script_path(file_name)
        items.append(
            {
                "title": script.title,
                "description": script.description,
                "python_requirements": script.python_requirements,
                "path": str(path),
            }
        )
    return {"count": len(items), "scripts": items}


async def _edit_script(arguments: dict[str, object]) -> dict[str, object]:
    title = _required_script_title(arguments.get("title"))
    existing = await get_script(title)
    if existing is None:
        raise RuntimeError(f"Script '{title}' not found.")

    changed = False
    description = existing.description
    instructions = existing.instructions
    python_requirements = existing.python_requirements
    body = existing.body

    if "description" in arguments:
        description = _required_limited_text(arguments.get("description"), "description", 1024)
        changed = True
    if "instructions" in arguments:
        instructions = _required_limited_text(arguments.get("instructions"), "instructions", 5000)
        changed = True
    if "python_requirements" in arguments or "requirements" in arguments:
        python_requirements = _optional_python_requirements(arguments)
        changed = True
    if "body" in arguments:
        body = _optional_text(arguments.get("body"))
        changed = True

    if not changed:
        raise RuntimeError(
            "No changes provided. Set at least one field: description, instructions, python_requirements, or body."
        )

    saved = await upsert_script(
        {
            "id": existing.id,
            "title": existing.title,
            "description": description,
            "instructions": instructions,
            "python_requirements": python_requirements,
            "body": body,
            "file_name": existing.file_name,
            "created_at": existing.created_at,
        },
        script_id=title,
    )
    rehydrate_stats = await rehydrate_script_files()
    return _script_payload(saved, "updated", rehydrate_stats)


async def _check_script_requirements_tool(arguments: dict[str, object]) -> dict[str, object]:
    title = _required_script_title(arguments.get("title"))
    script = await get_script(title)
    if script is None:
        raise RuntimeError(f"Script '{title}' not found.")
    return await _evaluate_script_requirements(script)


async def _install_script_requirements_tool(arguments: dict[str, object]) -> dict[str, object]:
    title = _required_script_title(arguments.get("title"))
    timeout_ms = _optional_timeout_ms(arguments.get("timeout_ms"), default_ms=180000, max_ms=300000)
    only_missing = bool(arguments.get("only_missing", True))

    script = await get_script(title)
    if script is None:
        raise RuntimeError(f"Script '{title}' not found.")

    check = await _evaluate_script_requirements(script)
    all_requirements = _as_string_list(check.get("python_requirements_list"))
    missing = _as_string_list(check.get("missing_requirements"))
    targets = missing if only_missing else all_requirements
    if len(targets) == 0:
        return {
            "status": "up_to_date",
            "title": script.title,
            "path": str(_resolve_script_path(script.file_name)),
            "installed": [],
            "stdout": "",
            "stderr": "",
            "exit_code": 0,
            "requirements_check": check,
        }

    install_result = await _run_pip_install(targets, timeout_ms=timeout_ms)
    return {
        "status": "installed" if install_result["exit_code"] == 0 else "error",
        "title": script.title,
        "path": str(_resolve_script_path(script.file_name)),
        "installed": targets,
        "stdout": install_result["stdout"],
        "stderr": install_result["stderr"],
        "exit_code": install_result["exit_code"],
    }


async def _execute_script(arguments: dict[str, object]) -> dict[str, object]:
    title = _required_script_title(arguments.get("title"))
    timeout_ms = _optional_timeout_ms(arguments.get("timeout_ms"), default_ms=30000, max_ms=120000)
    input_json = arguments.get("input_json")
    if input_json is None:
        input_json = {}
    if not isinstance(input_json, dict):
        raise RuntimeError("input_json must be a JSON object.")

    script = await get_script(title)
    if script is None:
        raise RuntimeError(f"Script '{title}' not found.")

    path = _resolve_script_path(script.file_name)
    temp_path: Path | None = None
    execution_path = path
    if not path.exists() or not path.is_file():
        temp_path = await _materialize_temp_script(script)
        execution_path = temp_path

    before_check = await _evaluate_script_requirements(script)
    install_result: dict[str, object] | None = None
    missing_before = _as_string_list(before_check.get("missing_requirements"))
    if missing_before:
        install_result = await _run_pip_install(missing_before, timeout_ms=180000)
        if install_result["exit_code"] != 0:
            await _cleanup_temp_script(temp_path)
            return {
                "status": "dependency_install_failed",
                "title": script.title,
                "path": str(path),
                "missing_requirements": missing_before,
                "pip": install_result,
            }

    after_check = await _evaluate_script_requirements(script)
    missing_after = _as_string_list(after_check.get("missing_requirements"))
    if missing_after:
        await _cleanup_temp_script(temp_path)
        return {
            "status": "requirements_missing",
            "title": script.title,
            "path": str(path),
            "missing_requirements": missing_after,
            "detail": "Some python requirements are still missing after install attempt.",
        }

    stdin_text = json.dumps(input_json, ensure_ascii=True)
    started = time.monotonic()
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        str(execution_path),
        stdin_text,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(stdin_text.encode("utf-8")),
            timeout=timeout_ms / 1000.0,
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        duration_ms = int((time.monotonic() - started) * 1000)
        await _cleanup_temp_script(temp_path)
        return {
            "status": "timeout",
            "title": script.title,
            "path": str(path),
            "timeout_ms": timeout_ms,
            "duration_ms": duration_ms,
            "stdout": "",
            "stderr": f"Script execution exceeded timeout of {timeout_ms} ms.",
            "exit_code": None,
            "requirements_check": after_check,
            "pip": install_result,
        }

    duration_ms = int((time.monotonic() - started) * 1000)
    stdout_text = _truncate_text(stdout_bytes.decode("utf-8", errors="replace"))
    stderr_text = _truncate_text(stderr_bytes.decode("utf-8", errors="replace"))
    exit_code = proc.returncode
    await _cleanup_temp_script(temp_path)
    return {
        "status": "ok" if exit_code == 0 else "error",
        "title": script.title,
        "path": str(path),
        "timeout_ms": timeout_ms,
        "duration_ms": duration_ms,
        "stdout": stdout_text,
        "stderr": stderr_text,
        "exit_code": exit_code,
        "requirements_check": after_check,
        "pip": install_result,
    }


async def _remove_script(arguments: dict[str, object]) -> dict[str, object]:
    title = _required_script_title(arguments.get("title"))
    existing = await get_script(title)
    if existing is None:
        raise RuntimeError(f"Script '{title}' not found.")

    path = _resolve_script_path(existing.file_name)
    deleted = await delete_script(title)
    if not deleted:
        raise RuntimeError(f"Script '{title}' could not be deleted.")

    await asyncio.to_thread(path.unlink, missing_ok=True)
    rehydrate_stats = await rehydrate_script_files()
    return {
        "status": "deleted",
        "id": title,
        "title": existing.title,
        "file_name": existing.file_name,
        "path": str(path),
        "rehydration": rehydrate_stats,
    }


async def _materialize_temp_script(script: object) -> Path:
    text = _render_script_source_from_record(script)
    def _create() -> Path:
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as handle:
            handle.write(text)
            return Path(handle.name)
    return await asyncio.to_thread(_create)


async def _cleanup_temp_script(path: Path | None) -> None:
    if path is None:
        return
    try:
        await asyncio.to_thread(path.unlink, missing_ok=True)
    except Exception:
        return


async def _evaluate_script_requirements(script: object) -> dict[str, object]:
    raw_value = str(getattr(script, "python_requirements", "") or "")
    parsed = _parse_python_requirements(raw_value)
    missing: list[str] = []
    installed: list[str] = []
    for item in parsed:
        if _is_requirement_installed(item):
            installed.append(item["raw"])
        else:
            missing.append(item["raw"])
    return {
        "title": str(getattr(script, "title", "")),
        "python_requirements": _stringify_requirements(parsed),
        "python_requirements_list": [item["raw"] for item in parsed],
        "installed_requirements": installed,
        "missing_requirements": missing,
        "ready": len(missing) == 0,
    }


async def _run_pip_install(requirements: list[str], *, timeout_ms: int) -> dict[str, object]:
    if len(requirements) == 0:
        return {"stdout": "", "stderr": "", "exit_code": 0, "timeout_ms": timeout_ms}

    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        *requirements,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=timeout_ms / 1000.0
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        return {
            "stdout": "",
            "stderr": f"pip install exceeded timeout of {timeout_ms} ms.",
            "exit_code": -1,
            "timeout_ms": timeout_ms,
        }
    return {
        "stdout": _truncate_text(stdout_bytes.decode("utf-8", errors="replace")),
        "stderr": _truncate_text(stderr_bytes.decode("utf-8", errors="replace")),
        "exit_code": proc.returncode,
        "timeout_ms": timeout_ms,
    }


def _is_requirement_installed(item: dict[str, str]) -> bool:
    package_name = item["name"]
    try:
        importlib_metadata.version(package_name)
        return True
    except importlib_metadata.PackageNotFoundError:
        return False


def _script_payload(saved: object, status: str, rehydrate_stats: dict[str, int]) -> dict[str, object]:
    file_name = str(getattr(saved, "file_name", ""))
    return {
        "status": status,
        "id": str(getattr(saved, "id", "")),
        "title": str(getattr(saved, "title", "")),
        "file_name": file_name,
        "path": str((SCRIPTS_DIR / file_name).resolve()),
        "metadata": {
            "description": str(getattr(saved, "description", "")),
            "instructions": str(getattr(saved, "instructions", "")),
            "python_requirements": str(getattr(saved, "python_requirements", "")),
        },
        "rehydration": rehydrate_stats,
    }


def _render_script_source_from_record(script: object) -> str:
    title = " ".join(str(getattr(script, "title", "")).split()).strip()
    description = " ".join(str(getattr(script, "description", "")).split()).strip()
    instructions = " ".join(str(getattr(script, "instructions", "")).split()).strip()
    python_requirements = " ".join(str(getattr(script, "python_requirements", "")).split()).strip()
    body = str(getattr(script, "body", "")).rstrip("\n")
    lines = [
        f"# krill-script-title: {title}",
        f"# krill-script-description: {description}",
        f"# krill-script-instructions: {instructions}",
        f"# krill-script-python-requirements: {python_requirements}",
        "",
    ]
    if body:
        lines.append(body)
        lines.append("")
    return "\n".join(lines)


def _required_script_title(value: object) -> str:
    if not isinstance(value, str):
        raise RuntimeError("Missing required argument 'title'.")
    title = value.strip()
    if not title:
        raise RuntimeError("Missing required argument 'title'.")
    if len(title) > 64:
        raise RuntimeError("title must be 64 characters or fewer.")
    if not _TITLE_PATTERN.fullmatch(title):
        raise RuntimeError(
            "title must match ^[a-z0-9]+(?:-[a-z0-9]+)*$ (lowercase letters, numbers, single hyphen separators)."
        )
    if "--" in title:
        raise RuntimeError("title must not contain consecutive hyphens.")
    return title


def _required_limited_text(value: object, field_name: str, max_length: int) -> str:
    if not isinstance(value, str):
        raise RuntimeError(f"Missing required argument '{field_name}'.")
    text = " ".join(value.split()).strip()
    if not text:
        raise RuntimeError(f"Missing required argument '{field_name}'.")
    if len(text) > max_length:
        raise RuntimeError(f"{field_name} must be {max_length} characters or fewer.")
    return text


def _optional_python_requirements(arguments: dict[str, object]) -> str:
    value = arguments.get("python_requirements", arguments.get("requirements"))
    if value is None:
        return ""
    if not isinstance(value, str):
        raise RuntimeError("python_requirements must be a string.")
    return _normalize_python_requirements(value)


def _normalize_python_requirements(value: str) -> str:
    if len(value) > 500:
        raise RuntimeError("python_requirements must be 500 characters or fewer.")
    if "\n" in value or "\r" in value:
        raise RuntimeError("python_requirements must be comma-separated on a single line.")
    parsed = _parse_python_requirements(value)
    return _stringify_requirements(parsed)


def _parse_python_requirements(value: str) -> list[dict[str, str]]:
    source = str(value or "").strip()
    if not source:
        return []
    tokens = [part.strip() for part in source.split(",")]
    if any(not token for token in tokens):
        raise RuntimeError("python_requirements contains an empty item. Use comma-separated items only.")

    parsed: list[dict[str, str]] = []
    seen = set()
    for token in tokens:
        match = _REQ_ITEM_PATTERN.fullmatch(token)
        if match is None:
            raise RuntimeError(
                f"Invalid python requirement '{token}'. Use format like 'requests' or 'requests>=2.31.0'."
            )
        name = str(match.group("name") or "").strip()
        specifier = str(match.group("specifier") or "").strip()
        normalized = f"{name}{specifier.replace(' ', '')}" if specifier else name
        dedupe_key = normalized.lower()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        parsed.append(
            {
                "name": name,
                "specifier": specifier.replace(" ", ""),
                "raw": normalized,
            }
        )
    return parsed


def _stringify_requirements(parsed: list[dict[str, str]]) -> str:
    if len(parsed) == 0:
        return ""
    return ", ".join(item["raw"] for item in parsed)


def _as_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        if isinstance(item, str):
            text = item.strip()
            if text:
                result.append(text)
    return result


def _optional_text(value: object) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise RuntimeError("body must be a string.")
    return value


def _optional_timeout_ms(value: object, *, default_ms: int, max_ms: int) -> int:
    if value is None:
        return default_ms
    if isinstance(value, bool):
        raise RuntimeError("timeout_ms must be an integer.")
    if isinstance(value, int):
        safe = value
    elif isinstance(value, float):
        safe = int(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return default_ms
        try:
            safe = int(text)
        except ValueError as exc:
            raise RuntimeError("timeout_ms must be an integer.") from exc
    else:
        raise RuntimeError("timeout_ms must be an integer.")
    return max(1000, min(max_ms, safe))


def _resolve_script_path(file_name: str) -> Path:
    clean = str(file_name or "").strip()
    if not clean:
        raise RuntimeError("Script has no file_name.")
    path = (SCRIPTS_DIR / clean).resolve()
    if path.parent != SCRIPTS_DIR:
        raise RuntimeError("Script path resolved outside script root.")
    return path


def _truncate_text(value: str, *, max_chars: int = 8000) -> str:
    text = value or ""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "...[truncated]"
