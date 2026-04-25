"""Scripts MCP plugin for creating and executing metadata-driven Python scripts."""

import asyncio
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from app.config import SCRIPTS_DIR, delete_script, get_script, is_script_title_enabled, list_scripts, upsert_script

from .base import MCPPlugin, McpConfigField, McpToolSpec

logger = logging.getLogger(__name__)


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
                description=(
                    "Edits an existing stored script by title. Security guard: only use this tool when "
                    "the user's current request explicitly says that a script should be edited. Do not "
                    "use it from implication, troubleshooting guesses, suggestions, or because a script "
                    "looks outdated; first ask for explicit confirmation that the script should be edited."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "minLength": 1, "maxLength": 120},
                        "description": {"type": "string", "minLength": 1, "maxLength": 1024},
                        "instructions": {"type": "string", "minLength": 1, "maxLength": 5000},
                        "python_requirements": {"type": "string", "maxLength": 500},
                        "body": {"type": "string"},
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
                        "title": {"type": "string", "minLength": 1, "maxLength": 120},
                        "only_missing": {"type": "boolean"},
                        "timeout_ms": {"type": "integer", "minimum": 1000, "maximum": 300000},
                    },
                    "required": ["title"],
                },
            ),
            McpToolSpec(
                id="execute_script",
                label="Execute Script",
                description="Auto-installs missing python requirements, then executes script by title. "
                "input_json keys are passed as --key value CLI arguments (e.g. {\"query\": \"hello\"} becomes --query hello).",
                input_schema={
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "minLength": 1, "maxLength": 120},
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
            "install_script_requirements",
            "execute_script",
            "remove_script",
        }:
            return ""
        return (
            "Scripts MCP reminder:\n"
            "- title must be lowercase letters/numbers/hyphens only and 1-64 chars.\n"
            "- python_requirements must be comma-separated pip requirement items.\n"
            "- execute_script auto-installs missing python requirements before running.\n"
            "- Scripts receive input_json keys as --key value CLI arguments; use argparse with named arguments.\n"
            "- description must be a use-case trigger (start with 'Use when...' or 'For...'), not a feature summary."
        )

    async def async_tool_call_system_reminder(
        self, tool_id: str, arguments: dict[str, object], params: dict[str, str],
    ) -> str:
        """Return a script-specific reminder that includes the target script's full instructions."""
        base = self.tool_call_system_reminder(tool_id, params)
        if tool_id == "create_script":
            return (
                f"{base}\n\n"
                "Script body guidance:\n"
                "- Scripts receive input_json as --key value CLI arguments.\n"
                "- Use argparse with named arguments matching expected input keys.\n"
                "- Always include an `if __name__ == \"__main__\":` guard.\n"
                "- Output results as JSON via `print(json.dumps(result))`.\n"
                "- Example pattern:\n"
                "    import argparse, json\n"
                "    parser = argparse.ArgumentParser()\n"
                "    parser.add_argument('--query', required=True)\n"
                "    args = parser.parse_args()\n"
                "    print(json.dumps({'result': args.query}))\n\n"
                "Description guidance (critical for orchestrator routing):\n"
                "- The description is how the orchestrator decides when to run this script.\n"
                "- Write it as a use-case trigger, not a feature summary.\n"
                "- Start with 'Use when...' or 'For...' followed by concrete user intents.\n"
                "- Include key trigger words and phrases a user would naturally say.\n"
                "- Bad example: 'A script that checks the weather.'\n"
                "- Good example: 'Use when the user asks about weather, temperature, forecast, "
                "or climate conditions for a city or location.'\n"
                "- Keep under 300 characters; that is all the orchestrator sees.\n\n"
                "Instructions guidance:\n"
                "- The first 220 characters of instructions are visible to the orchestrator during planning.\n"
                "- Front-load the most important usage context into those first 220 characters.\n"
                "- Include expected input_json keys and their meaning early.\n"
                "- Put detailed edge-case handling or output format notes after the first 220 characters."
            )
        if tool_id != "execute_script":
            return base
        raw_title = arguments.get("title")
        if not isinstance(raw_title, str) or not raw_title.strip():
            return base
        try:
            script = await _resolve_script_for_execution(raw_title.strip())
        except Exception:
            return base
        instructions = str(getattr(script, "instructions", "")).strip()
        if not instructions:
            return base
        return (
            f"{base}\n\n"
            f"Target script: {getattr(script, 'title', raw_title)}\n"
            f"Script instructions:\n{instructions}"
        )

    async def call_tool(self, tool_id: str, arguments: dict[str, object], params: dict[str, str]) -> dict[str, object]:
        if tool_id == "create_script":
            return await _create_script(arguments)
        if tool_id == "list_scripts":
            return await _list_scripts_tool()
        if tool_id == "edit_script":
            return await _edit_script(arguments)
        if tool_id == "install_script_requirements":
            return await _install_script_requirements_tool(arguments)
        if tool_id == "execute_script":
            requested_title = _required_script_query(arguments.get("title"))
            resolved_script = await _resolve_script_for_execution(requested_title)
            if not is_script_title_enabled(str(getattr(resolved_script, "title", "")), params):
                raise RuntimeError(f"Script '{getattr(resolved_script, 'title', requested_title)}' is disabled in Scripts MCP settings.")
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
    record = {
        "id": title,
        "title": title,
        "description": description,
        "instructions": instructions,
        "python_requirements": python_requirements,
        "body": body,
        "file_name": file_name,
    }
    candidate_source = _render_script_source_from_record(
        type("_S", (), record)()
    )
    _validate_script_metadata_headers(candidate_source)

    saved = await upsert_script(record, script_id=title)
    return _script_payload(saved, "updated" if existing is not None else "created")


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
                "instructions": script.instructions,
                "python_requirements": script.python_requirements,
                "path": str(path),
            }
        )
    return {"count": len(items), "scripts": items}


async def _edit_script(arguments: dict[str, object]) -> dict[str, object]:
    title = _required_script_query(arguments.get("title"))
    existing = await _resolve_script_for_execution(title)

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

    record = {
        "id": existing.id,
        "title": existing.title,
        "description": description,
        "instructions": instructions,
        "python_requirements": python_requirements,
        "body": body,
        "file_name": existing.file_name,
        "created_at": existing.created_at,
    }
    candidate_source = _render_script_source_from_record(
        type("_S", (), record)()
    )
    _validate_script_metadata_headers(candidate_source)

    saved = await upsert_script(record, script_id=str(existing.id))
    return _script_payload(saved, "updated")


async def _install_script_requirements_tool(arguments: dict[str, object]) -> dict[str, object]:
    title = _required_script_query(arguments.get("title"))
    timeout_ms = _optional_timeout_ms(arguments.get("timeout_ms"), default_ms=180000, max_ms=300000)

    script = await _resolve_script_for_execution(title)
    parsed = _parse_python_requirements(str(getattr(script, "python_requirements", "") or ""))
    requirements = [item["raw"] for item in parsed]

    if not requirements:
        return {
            "status": "up_to_date",
            "title": script.title,
            "path": str(_resolve_script_path(script.file_name)),
            "requirements": [],
            "stdout": "",
            "stderr": "",
            "exit_code": 0,
        }

    install_result = await _run_pip_install(requirements, timeout_ms=timeout_ms)
    return {
        "status": "installed" if install_result["exit_code"] == 0 else "error",
        "title": script.title,
        "path": str(_resolve_script_path(script.file_name)),
        "requirements": requirements,
        "stdout": install_result["stdout"],
        "stderr": install_result["stderr"],
        "exit_code": install_result["exit_code"],
    }


async def _execute_script(arguments: dict[str, object]) -> dict[str, object]:
    try:
        return await _execute_script_inner(arguments)
    except Exception as exc:
        exc_type = type(exc).__name__
        exc_msg = str(exc).strip() or "(no message)"
        logger.error("execute_script FAILED: %s: %s", exc_type, exc_msg, exc_info=True)
        raise RuntimeError(f"execute_script failed: {exc_type}: {exc_msg}") from exc


async def _execute_script_inner(arguments: dict[str, object]) -> dict[str, object]:
    logger.info("execute_script called with arguments: %s", json.dumps({k: str(v)[:200] for k, v in arguments.items()}, ensure_ascii=True))
    title = _required_script_query(arguments.get("title"))
    timeout_ms = _optional_timeout_ms(arguments.get("timeout_ms"), default_ms=30000, max_ms=120000)
    input_json = _normalize_script_input_payload(arguments.get("input_json"))

    logger.info("execute_script resolved title=%r, timeout_ms=%d", title, timeout_ms)
    script = await _resolve_script_for_execution(title)
    logger.info("execute_script resolved script id=%s title=%s", getattr(script, "id", "?"), getattr(script, "title", "?"))

    # Always use a temp file for execution to avoid stale data/scripts/ files
    # and to prevent uvicorn --reload from being triggered by writes to data/scripts/.
    temp_path = await _materialize_temp_script(script)
    execution_path = temp_path
    logger.info("execute_script using temp file at %s", execution_path)

    # Always run pip install for all requirements — fast "already satisfied" when up to date,
    # correct install when missing. Avoids fragile in-process name-matching checks.
    parsed_reqs = _parse_python_requirements(str(getattr(script, "python_requirements", "") or ""))
    requirements = [item["raw"] for item in parsed_reqs]
    install_result: dict[str, object] | None = None
    if requirements:
        # Cap pip install timeout to leave room for actual script execution within the
        # orchestrator's overall tool_timeout_seconds (typically 90s).
        pip_timeout = min(timeout_ms, 60000)
        logger.info("execute_script installing requirements: %s (pip timeout=%dms)", requirements, pip_timeout)
        install_result = await _run_pip_install(requirements, timeout_ms=pip_timeout)
        if install_result["exit_code"] != 0:
            await _cleanup_temp_script(temp_path)
            return {
                "status": "dependency_install_failed",
                "title": script.title,
                "path": str(_resolve_script_path(script.file_name)),
                "requirements": requirements,
                "pip": install_result,
            }

    stdin_text = json.dumps(input_json, ensure_ascii=True)
    named_args = _build_named_args_from_input(input_json)
    cli_args = _build_cli_args_from_input(input_json)
    started = time.monotonic()
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    logger.info("execute_script running script at %s with named_args=%s cli_args=%s", execution_path, named_args, cli_args)
    execution_result = await _run_script_process_attempts(
        execution_path=execution_path,
        stdin_text=stdin_text,
        timeout_ms=timeout_ms,
        env=env,
        cli_args=cli_args,
        named_args=named_args,
    )
    if execution_result.get("timeout"):
        duration_ms = int((time.monotonic() - started) * 1000)
        await _cleanup_temp_script(temp_path)
        return {
            "status": "timeout",
            "title": script.title,
            "path": str(_resolve_script_path(script.file_name)),
            "timeout_ms": timeout_ms,
            "duration_ms": duration_ms,
            "stdout": "",
            "stderr": f"Script execution exceeded timeout of {timeout_ms} ms.",
            "exit_code": None,
            "pip": install_result,
        }

    duration_ms = int((time.monotonic() - started) * 1000)
    stdout_text = str(execution_result.get("stdout", ""))
    stderr_text = str(execution_result.get("stderr", ""))
    exit_code = int(execution_result.get("exit_code", -1))
    logger.info(
        "execute_script completed: exit_code=%s mode=%s duration_ms=%d stdout_len=%d stderr_len=%d",
        exit_code, execution_result.get("mode", "?"), duration_ms, len(stdout_text), len(stderr_text),
    )
    if exit_code != 0:
        logger.warning("execute_script non-zero exit: stderr=%s", stderr_text[:500])
    await _cleanup_temp_script(temp_path)
    return {
        "status": "ok" if exit_code == 0 else "error",
        "title": script.title,
        "path": str(_resolve_script_path(script.file_name)),
        "timeout_ms": timeout_ms,
        "duration_ms": duration_ms,
        "stdout": stdout_text,
        "stderr": stderr_text,
        "exit_code": exit_code,
        "pip": install_result,
        "execution_mode": str(execution_result.get("mode", "unknown")),
    }


async def _remove_script(arguments: dict[str, object]) -> dict[str, object]:
    title = _required_script_query(arguments.get("title"))
    existing = await _resolve_script_for_execution(title)
    if existing is None:
        raise RuntimeError(f"Script '{title}' not found.")

    path = _resolve_script_path(existing.file_name)
    deleted = await delete_script(str(existing.id))
    if not deleted:
        raise RuntimeError(f"Script '{title}' could not be deleted.")

    await asyncio.to_thread(path.unlink, missing_ok=True)
    return {
        "status": "deleted",
        "id": title,
        "title": existing.title,
        "file_name": existing.file_name,
        "path": str(path),
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


async def _resolve_script_for_execution(requested_title: str) -> object:
    exact = await get_script(requested_title)
    if exact is not None:
        return exact

    scripts = await list_scripts()
    if len(scripts) == 1:
        return scripts[0]

    lowered = requested_title.lower()
    query_tokens = set(re.findall(r"[a-z0-9]+", lowered))
    best: object | None = None
    best_score = -1
    for script in scripts:
        title = str(getattr(script, "title", "")).strip()
        description = str(getattr(script, "description", "")).strip().lower()
        instructions = str(getattr(script, "instructions", "")).strip().lower()
        if not title:
            continue
        title_lower = title.lower()
        title_words = set(re.findall(r"[a-z0-9]+", title_lower))
        exact_phrase = title_lower in lowered or title_lower.replace("-", " ") in lowered
        overlap = len(title_words.intersection(query_tokens))
        semantic_overlap = len(set(re.findall(r"[a-z0-9]+", f"{description} {instructions}")).intersection(query_tokens))
        score = (100 if exact_phrase else 0) + overlap * 3 + semantic_overlap
        if score > best_score:
            best_score = score
            best = script

    if best is not None and best_score > 0:
        return best
    raise RuntimeError(f"Script '{requested_title}' not found.")


def _normalize_script_input_payload(value: object) -> dict[str, object]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, bool):
        return {"value": value}
    if isinstance(value, int | float):
        return _number_payload(int(value))
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return {}
        try:
            decoded = json.loads(text)
            if isinstance(decoded, dict):
                return decoded
            if isinstance(decoded, int | float):
                return _number_payload(int(decoded))
            if isinstance(decoded, list):
                return {"args": decoded, "argv": decoded}
        except Exception:
            pass
        if re.fullmatch(r"-?\d+", text):
            return _number_payload(int(text))
        return {"input": text, "value": text}
    if isinstance(value, list):
        payload: dict[str, object] = {"args": value, "argv": value}
        first = value[0] if value else None
        if isinstance(first, int | float):
            payload.update(_number_payload(int(first)))
        elif isinstance(first, str) and re.fullmatch(r"-?\d+", first.strip()):
            payload.update(_number_payload(int(first.strip())))
        return payload
    return {"value": str(value)}


def _number_payload(number: int) -> dict[str, object]:
    return {
        "limit": number,
        "count": number,
        "n": number,
        "number": number,
        "value": number,
        "input": number,
        "to": number,
    }


_NAMED_ARGS_SKIP_KEYS = {"args", "argv"}


def _build_named_args_from_input(input_payload: dict[str, object]) -> list[str]:
    """Convert input_json keys to ``--key value`` CLI arguments for argparse-based scripts.

    Only scalar values (str, int, float, bool) are emitted.  Keys whose values
    are dicts, lists, or None are silently skipped, as are meta keys produced by
    ``_normalize_script_input_payload`` (``args``, ``argv``).
    """
    result: list[str] = []
    for key, value in input_payload.items():
        if key in _NAMED_ARGS_SKIP_KEYS:
            continue
        if isinstance(value, bool):
            result.extend([f"--{key}", str(value).lower()])
        elif isinstance(value, int | float):
            result.extend([f"--{key}", str(value)])
        elif isinstance(value, str):
            result.extend([f"--{key}", value])
        # dicts, lists, None → skip
    return result


def _build_cli_args_from_input(input_payload: dict[str, object]) -> list[str]:
    if len(input_payload) == 0:
        return []
    numeric_keys = ["n", "limit", "count", "number", "value", "input", "to"]
    for key in numeric_keys:
        value = input_payload.get(key)
        if isinstance(value, int | float):
            return [str(int(value))]
        if isinstance(value, str) and re.fullmatch(r"-?\d+", value.strip()):
            return [value.strip()]

    args = input_payload.get("args")
    if isinstance(args, list):
        values = [str(item) for item in args if str(item).strip()]
        if values:
            return values
    argv = input_payload.get("argv")
    if isinstance(argv, list):
        values = [str(item) for item in argv if str(item).strip()]
        if values:
            return values
    return []


async def _run_script_process_attempts(
    *,
    execution_path: Path,
    stdin_text: str,
    timeout_ms: int,
    env: dict[str, str],
    cli_args: list[str],
    named_args: list[str] | None = None,
) -> dict[str, object]:
    """Run a script with multiple argument strategies, using subprocess.run in a thread.

    Strategy order: named_args → json_argv → positional_args → stdin_only.

    Uses synchronous subprocess.run via asyncio.to_thread instead of
    asyncio.create_subprocess_exec because the latter requires ProactorEventLoop
    on Windows, which uvicorn does not guarantee.
    """
    attempts: list[tuple[str, list[str]]] = []
    if named_args:
        attempts.append(("named_args", named_args))
    attempts.append(("json_argv", [stdin_text]))
    if cli_args:
        attempts.append(("positional_args", cli_args))
    attempts.append(("stdin_only", []))

    last_result: dict[str, object] = {
        "mode": "none",
        "exit_code": -1,
        "stdout": "",
        "stderr": "",
        "timeout": False,
    }
    timeout_seconds = timeout_ms / 1000.0

    for mode, argv in attempts:
        cmd = [sys.executable, str(execution_path)] + argv

        def _run_process(command: list[str] = cmd, attempt_mode: str = mode) -> dict[str, object]:
            try:
                result = subprocess.run(
                    command,
                    input=stdin_text.encode("utf-8"),
                    capture_output=True,
                    timeout=timeout_seconds,
                    env=env,
                )
                return {
                    "mode": attempt_mode,
                    "exit_code": result.returncode,
                    "stdout": _truncate_text(result.stdout.decode("utf-8", errors="replace")),
                    "stderr": _truncate_text(result.stderr.decode("utf-8", errors="replace")),
                    "timeout": False,
                }
            except subprocess.TimeoutExpired:
                return {
                    "mode": attempt_mode,
                    "exit_code": None,
                    "stdout": "",
                    "stderr": f"Script execution exceeded timeout of {timeout_ms} ms.",
                    "timeout": True,
                }

        attempt_result = await asyncio.to_thread(_run_process)

        if attempt_result.get("timeout"):
            return attempt_result

        last_result = attempt_result
        if attempt_result.get("exit_code") == 0:
            return last_result
    return last_result


async def _run_pip_install(requirements: list[str], *, timeout_ms: int) -> dict[str, object]:
    """Install pip requirements using subprocess.run in a thread.

    Uses synchronous subprocess.run via asyncio.to_thread instead of
    asyncio.create_subprocess_exec for Windows compatibility (ProactorEventLoop).
    """
    if len(requirements) == 0:
        return {"stdout": "", "stderr": "", "exit_code": 0, "timeout_ms": timeout_ms}

    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    cmd = [
        sys.executable, "-m", "pip", "install",
        "--disable-pip-version-check",
        *requirements,
    ]
    timeout_seconds = timeout_ms / 1000.0

    def _run() -> dict[str, object]:
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=timeout_seconds,
                env=env,
            )
            return {
                "stdout": _truncate_text(result.stdout.decode("utf-8", errors="replace")),
                "stderr": _truncate_text(result.stderr.decode("utf-8", errors="replace")),
                "exit_code": result.returncode,
                "timeout_ms": timeout_ms,
            }
        except subprocess.TimeoutExpired:
            return {
                "stdout": "",
                "stderr": f"pip install exceeded timeout of {timeout_ms} ms.",
                "exit_code": -1,
                "timeout_ms": timeout_ms,
            }

    return await asyncio.to_thread(_run)


def _script_payload(saved: object, status: str) -> dict[str, object]:
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


def _parse_script_source(source: str) -> dict[str, str]:
    """Parse a full script source (with krill-script-* metadata headers) back into components.

    Returns dict with keys: title, description, instructions, python_requirements, body.
    """
    title = ""
    description = ""
    instructions = ""
    python_requirements = ""
    body_lines: list[str] = []
    in_body = False

    for line in source.split("\n"):
        if not in_body and line.startswith("# krill-script-title:"):
            title = line[len("# krill-script-title:"):].strip()
        elif not in_body and line.startswith("# krill-script-description:"):
            description = line[len("# krill-script-description:"):].strip()
        elif not in_body and line.startswith("# krill-script-instructions:"):
            instructions = line[len("# krill-script-instructions:"):].strip()
        elif not in_body and line.startswith("# krill-script-python-requirements:"):
            python_requirements = line[len("# krill-script-python-requirements:"):].strip()
        elif not in_body and line.strip() == "":
            # First blank line after headers marks start of body
            if title:
                in_body = True
        else:
            in_body = True
            body_lines.append(line)

    body = "\n".join(body_lines).strip()
    return {
        "title": title,
        "description": description,
        "instructions": instructions,
        "python_requirements": python_requirements,
        "body": body,
    }


def _validate_script_metadata_headers(source: str) -> None:
    """Validate that *source* starts with exactly 4 krill-script-* header lines in the correct order.

    Raises ``RuntimeError`` with an actionable message on any violation.
    """
    lines = source.split("\n")
    if len(lines) < 4:
        raise RuntimeError(
            "Script must start with 4 metadata header lines: "
            "# krill-script-title, # krill-script-description, "
            "# krill-script-instructions, # krill-script-python-requirements."
        )

    _HEADER_PREFIXES = [
        "# krill-script-title:",
        "# krill-script-description:",
        "# krill-script-instructions:",
        "# krill-script-python-requirements:",
    ]
    _HEADER_NAMES = ["title", "description", "instructions", "python-requirements"]

    for idx, (prefix, name) in enumerate(zip(_HEADER_PREFIXES, _HEADER_NAMES)):
        line = lines[idx]
        if not line.startswith(prefix):
            raise RuntimeError(
                f"Line {idx + 1} must start with '{prefix}' but got: {line!r}"
            )

    # --- title (line 1) ---
    title_value = lines[0][len(_HEADER_PREFIXES[0]):].strip()
    _required_script_title(title_value)

    # --- description (line 2) ---
    desc_value = lines[1][len(_HEADER_PREFIXES[1]):].strip()
    _required_limited_text(desc_value, "description", 1024)

    # --- instructions (line 3) ---
    instr_value = lines[2][len(_HEADER_PREFIXES[2]):].strip()
    _required_limited_text(instr_value, "instructions", 5000)

    # --- python_requirements (line 4) ---
    reqs_value = lines[3][len(_HEADER_PREFIXES[3]):].strip()
    if reqs_value:
        _normalize_python_requirements(reqs_value)


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


def _required_script_query(value: object) -> str:
    if not isinstance(value, str):
        raise RuntimeError("Missing required argument 'title'.")
    text = " ".join(value.split()).strip()
    if not text:
        raise RuntimeError("Missing required argument 'title'.")
    if len(text) > 120:
        raise RuntimeError("title must be 120 characters or fewer.")
    return text


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
