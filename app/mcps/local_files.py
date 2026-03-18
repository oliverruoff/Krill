"""Local file MCP plugin for filesystem search, edits, and command execution."""

import asyncio
import fnmatch
import os
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlparse, unquote

from app.config import BASE_DIR
from app.shared_files import create_shared_file_link

from .base import MCPPlugin, McpConfigField, McpToolSpec


DEFAULT_EXCLUDED_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    "dist",
    "build",
    "target",
    "$Recycle.Bin",
}
_SHARE_FILE_MAX_BYTES = 25 * 1024 * 1024
_PUBLIC_BASE_URL_PARAM = "public_base_url"


class LocalFilesMCP(MCPPlugin):
    mcp_id = "local_files"
    display_name = "Local Files"
    description = "Searches, reads, writes, edits, copies, moves, deletes, and executes local filesystem tasks."
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
                id="list_directory",
                label="List Directory",
                description="Lists files and folders in a directory.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "max_entries": {"type": "integer", "minimum": 1, "maximum": 2000},
                        "include_excluded": {"type": "boolean"},
                    },
                },
            ),
            McpToolSpec(
                id="glob_files",
                label="Glob Files",
                description="Finds files by glob pattern.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string", "minLength": 1},
                        "base_path": {"type": "string"},
                        "max_results": {"type": "integer", "minimum": 1, "maximum": 5000},
                        "include_excluded": {"type": "boolean"},
                    },
                    "required": ["pattern"],
                },
            ),
            McpToolSpec(
                id="search_content",
                label="Search Content",
                description="Searches file contents with regex.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string", "minLength": 1},
                        "base_path": {"type": "string"},
                        "include": {"type": "string"},
                        "max_results": {"type": "integer", "minimum": 1, "maximum": 5000},
                        "include_excluded": {"type": "boolean"},
                        "case_insensitive": {"type": "boolean"},
                    },
                    "required": ["pattern"],
                },
            ),
            McpToolSpec(
                id="grep",
                label="Grep",
                description="Greps file contents with regex and returns matching lines.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string", "minLength": 1},
                        "base_path": {"type": "string"},
                        "include": {"type": "string"},
                        "max_results": {"type": "integer", "minimum": 1, "maximum": 5000},
                        "include_excluded": {"type": "boolean"},
                        "case_insensitive": {"type": "boolean"},
                    },
                    "required": ["pattern"],
                },
            ),
            McpToolSpec(
                id="read_file",
                label="Read File",
                description="Reads a text file with optional line window.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "minLength": 1},
                        "offset": {"type": "integer", "minimum": 1},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 2000},
                    },
                    "required": ["path"],
                },
            ),
            McpToolSpec(
                id="write_file",
                label="Write File",
                description="Writes text content to a file path.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "minLength": 1},
                        "content": {"type": "string"},
                        "overwrite": {"type": "boolean"},
                        "create_parent_dirs": {"type": "boolean"},
                    },
                    "required": ["path", "content"],
                },
            ),
            McpToolSpec(
                id="edit_file",
                label="Edit File",
                description="Edits a text file using find/replace.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "minLength": 1},
                        "find": {"type": "string", "minLength": 1},
                        "replace": {"type": "string"},
                        "replace_all": {"type": "boolean"},
                        "require_match": {"type": "boolean"},
                    },
                    "required": ["path", "find", "replace"],
                },
            ),
            McpToolSpec(
                id="copy_path",
                label="Copy Path",
                description="Copies a file or directory to a destination path.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "source_path": {"type": "string", "minLength": 1},
                        "destination_path": {"type": "string", "minLength": 1},
                        "overwrite": {"type": "boolean"},
                        "recursive": {"type": "boolean"},
                        "create_parent_dirs": {"type": "boolean"},
                    },
                    "required": ["source_path", "destination_path"],
                },
            ),
            McpToolSpec(
                id="move_path",
                label="Move Path",
                description="Moves a file or directory to a destination path.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "source_path": {"type": "string", "minLength": 1},
                        "destination_path": {"type": "string", "minLength": 1},
                        "overwrite": {"type": "boolean"},
                        "create_parent_dirs": {"type": "boolean"},
                    },
                    "required": ["source_path", "destination_path"],
                },
            ),
            McpToolSpec(
                id="delete_path",
                label="Delete Path",
                description="Deletes a file or directory. Requires confirm=true.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "minLength": 1},
                        "confirm": {"type": "boolean"},
                        "recursive": {"type": "boolean"},
                    },
                    "required": ["path", "confirm"],
                },
            ),
            McpToolSpec(
                id="execute_command",
                label="Execute Command",
                description="Executes a shell command in a working directory.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "minLength": 1},
                        "workdir": {"type": "string"},
                        "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 300},
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
        if tool_id in {"list_directory", "glob_files", "search_content", "grep", "read_file"}:
            return ""
        if tool_id == "share_file":
            return (
                "After calling share_file, include the returned download_url in your response exactly as returned. "
                "Never invent or rewrite host/port for shared links. "
                "For Telegram, keep the URL present in output so the integration can send the file as a document."
            )
        return (
            "Local Files safety reminder:\n"
            "- For write/edit/copy/move/delete/execute actions, follow explicit user intent only.\n"
            "- Do not perform destructive actions unless requested; require clear target paths.\n"
            "- For delete_path, confirm must be true.\n"
            "- Return JSON only with this shape: {\"arguments\":{...}}"
        )

    async def verify(self, params: dict[str, str]) -> tuple[bool, str]:
        return True, "Local Files MCP is ready without setup."

    async def call_tool(self, tool_id: str, arguments: dict[str, object], params: dict[str, str]) -> dict[str, object]:
        if tool_id == "list_directory":
            path = _resolve_base_path(_optional_str(arguments, "path", str(BASE_DIR)))
            max_entries = _optional_int(arguments, "max_entries", 500, 1, 2000)
            include_excluded = bool(arguments.get("include_excluded", False))
            entries = await asyncio.to_thread(_list_directory, path, max_entries, include_excluded)
            return {
                "path": str(path),
                "entries": entries,
            }

        if tool_id == "glob_files":
            pattern = _required_str(arguments, "pattern")
            base_path_raw = _optional_str(arguments, "base_path", _optional_str(arguments, "path", str(BASE_DIR)))
            base_path = _resolve_base_path(base_path_raw)
            max_results = _optional_int(arguments, "max_results", 500, 1, 5000)
            include_excluded = bool(arguments.get("include_excluded", False))
            results = await asyncio.to_thread(_glob_files, base_path, pattern, max_results, include_excluded)
            return {
                "base_path": str(base_path),
                "pattern": pattern,
                "results": results,
            }

        if tool_id == "search_content" or tool_id == "grep":
            pattern = _required_str(arguments, "pattern")
            base_path_raw = _optional_str(arguments, "base_path", _optional_str(arguments, "path", str(BASE_DIR)))
            base_path = _resolve_base_path(base_path_raw)
            include = _optional_str(arguments, "include", "")
            max_results = _optional_int(arguments, "max_results", 200, 1, 5000)
            include_excluded = bool(arguments.get("include_excluded", False))
            case_insensitive = bool(arguments.get("case_insensitive", True))
            results = await asyncio.to_thread(
                _search_content,
                base_path,
                pattern,
                include,
                max_results,
                include_excluded,
                case_insensitive,
            )
            return {
                "base_path": str(base_path),
                "pattern": pattern,
                "include": include,
                "results": results,
            }

        if tool_id == "read_file":
            file_path = _resolve_base_path(_required_str(arguments, "path"))
            offset = _optional_int(arguments, "offset", 1, 1, 1_000_000)
            limit = _optional_int(arguments, "limit", 400, 1, 2000)
            content = await asyncio.to_thread(_read_file, file_path, offset, limit)
            return {
                "path": str(file_path),
                "offset": offset,
                "limit": limit,
                "content": content,
            }

        if tool_id == "write_file":
            path = _resolve_path(_required_str(arguments, "path"), must_exist=False)
            content = _required_string_like(arguments, "content")
            overwrite = bool(arguments.get("overwrite", True))
            create_parent_dirs = bool(arguments.get("create_parent_dirs", True))
            result = await asyncio.to_thread(_write_file_text, path, content, overwrite, create_parent_dirs)
            return result

        if tool_id == "edit_file":
            path = _resolve_base_path(_required_str(arguments, "path"))
            find_value = _required_str(arguments, "find")
            replace_value = _required_string_like(arguments, "replace")
            replace_all = bool(arguments.get("replace_all", False))
            require_match = bool(arguments.get("require_match", True))
            result = await asyncio.to_thread(_edit_file_text, path, find_value, replace_value, replace_all, require_match)
            return result

        if tool_id == "copy_path":
            source_path = _resolve_base_path(_required_str(arguments, "source_path"))
            destination_path = _resolve_path(_required_str(arguments, "destination_path"), must_exist=False)
            overwrite = bool(arguments.get("overwrite", False))
            recursive = bool(arguments.get("recursive", False))
            create_parent_dirs = bool(arguments.get("create_parent_dirs", True))
            result = await asyncio.to_thread(
                _copy_path,
                source_path,
                destination_path,
                overwrite,
                recursive,
                create_parent_dirs,
            )
            return result

        if tool_id == "move_path":
            source_path = _resolve_base_path(_required_str(arguments, "source_path"))
            destination_path = _resolve_path(_required_str(arguments, "destination_path"), must_exist=False)
            overwrite = bool(arguments.get("overwrite", False))
            create_parent_dirs = bool(arguments.get("create_parent_dirs", True))
            result = await asyncio.to_thread(_move_path, source_path, destination_path, overwrite, create_parent_dirs)
            return result

        if tool_id == "delete_path":
            path = _resolve_base_path(_required_str(arguments, "path"))
            confirm = bool(arguments.get("confirm", False))
            recursive = bool(arguments.get("recursive", False))
            result = await asyncio.to_thread(_delete_path, path, confirm, recursive)
            return result

        if tool_id == "execute_command":
            command = _required_str(arguments, "command")
            workdir_raw = _optional_str(arguments, "workdir", str(BASE_DIR))
            workdir = _resolve_base_path(workdir_raw)
            timeout_seconds = _optional_int(arguments, "timeout_seconds", 45, 1, 300)
            result = await asyncio.to_thread(_execute_command, command, workdir, timeout_seconds)
            return result

        if tool_id == "share_file":
            file_path = _resolve_base_path(_required_str(arguments, "path"))
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

        raise RuntimeError(f"Unsupported Local Files tool: {tool_id}")


def _resolve_base_path(raw_path: str) -> Path:
    return _resolve_path(raw_path, must_exist=True)


def _resolve_path(raw_path: str, *, must_exist: bool) -> Path:
    candidates = _path_candidates(raw_path)
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if resolved.exists():
            return resolved

    first = candidates[0].expanduser().resolve() if candidates else Path(raw_path).expanduser().resolve()
    if not must_exist:
        return first

    raise RuntimeError(f"Path does not exist: {first}")


def _path_candidates(raw_path: str) -> list[Path]:
    text = str(raw_path or "").strip()
    if not text:
        return [BASE_DIR]

    # Trim wrapping quotes often produced by copied shell snippets.
    if len(text) >= 2 and ((text[0] == '"' and text[-1] == '"') or (text[0] == "'" and text[-1] == "'")):
        text = text[1:-1].strip()

    # Handle file:// URLs pasted from browsers/tools.
    if text.lower().startswith("file://"):
        parsed = urlparse(text)
        file_path = unquote(parsed.path or "")
        if parsed.netloc:
            file_path = f"//{parsed.netloc}{file_path}"
        if os.name == "nt" and file_path.startswith("/") and len(file_path) > 2 and file_path[2] == ":":
            file_path = file_path[1:]
        text = file_path.strip()

    variants: list[str] = [text]

    stripped_slash = text.rstrip("\\/")
    if stripped_slash and stripped_slash != text:
        variants.append(stripped_slash)

    if "\\\\" in text:
        variants.append(text.replace("\\\\", "\\"))

    if "\\" in text:
        variants.append(text.replace("\\", "/"))

    if _looks_windows_absolute_path(text):
        mapped = _map_windows_path_to_base_dir(text)
        if mapped is not None:
            variants.append(str(mapped))

    results: list[Path] = []
    seen: set[str] = set()
    for variant in variants:
        normalized = variant.strip()
        if not normalized:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)

        path = Path(normalized)
        results.append(path)
        if not path.is_absolute() and not _looks_windows_absolute_path(normalized):
            results.append(BASE_DIR / path)

    return results or [BASE_DIR]


def _looks_windows_absolute_path(value: str) -> bool:
    return bool(re.match(r"^[a-zA-Z]:[\\/]", value))


def _map_windows_path_to_base_dir(raw_path: str) -> Path | None:
    text = raw_path.strip()
    if not _looks_windows_absolute_path(text):
        return None

    without_drive = re.sub(r"^[a-zA-Z]:", "", text)
    parts = [part for part in re.split(r"[\\/]+", without_drive) if part]
    if not parts:
        return None

    base_name = BASE_DIR.name.casefold()
    target_index = -1
    for index, part in enumerate(parts):
        if part.casefold() == base_name:
            target_index = index
            break

    if target_index == -1:
        return None

    relative_parts = parts[target_index + 1 :]
    if not relative_parts:
        return BASE_DIR

    return BASE_DIR.joinpath(*relative_parts)


def _list_directory(path: Path, max_entries: int, include_excluded: bool) -> list[dict[str, str]]:
    if not path.is_dir():
        raise RuntimeError(f"Path is not a directory: {path}")

    entries: list[dict[str, str]] = []
    for item in sorted(path.iterdir(), key=lambda p: p.name.lower()):
        if not include_excluded and _is_excluded(item):
            continue

        entries.append(
            {
                "name": item.name,
                "path": str(item),
                "type": "dir" if item.is_dir() else "file",
            }
        )

        if len(entries) >= max_entries:
            break

    return entries


def _glob_files(base_path: Path, pattern: str, max_results: int, include_excluded: bool) -> list[str]:
    if not base_path.is_dir():
        raise RuntimeError(f"Base path is not a directory: {base_path}")

    results: list[str] = []
    for root, dirs, files in os.walk(base_path):
        root_path = Path(root)
        if not include_excluded:
            dirs[:] = [entry for entry in dirs if not _is_excluded(root_path / entry)]

        for filename in files:
            file_path = root_path / filename
            if not include_excluded and _is_excluded(file_path):
                continue

            rel_path = file_path.relative_to(base_path).as_posix()
            if fnmatch.fnmatch(rel_path, pattern) or fnmatch.fnmatch(filename, pattern):
                results.append(str(file_path))
                if len(results) >= max_results:
                    return results

    return results


def _search_content(
    base_path: Path,
    pattern: str,
    include: str,
    max_results: int,
    include_excluded: bool,
    case_insensitive: bool,
) -> list[dict[str, object]]:
    if not base_path.is_dir():
        raise RuntimeError(f"Base path is not a directory: {base_path}")

    flags = re.IGNORECASE if case_insensitive else 0
    try:
        regex = re.compile(pattern, flags)
    except re.error as exc:
        raise RuntimeError(f"Invalid regex pattern: {exc}") from exc

    matches: list[dict[str, object]] = []
    for root, dirs, files in os.walk(base_path):
        root_path = Path(root)
        if not include_excluded:
            dirs[:] = [entry for entry in dirs if not _is_excluded(root_path / entry)]

        for filename in files:
            file_path = root_path / filename
            if not include_excluded and _is_excluded(file_path):
                continue

            if include and not (fnmatch.fnmatch(filename, include) or fnmatch.fnmatch(file_path.as_posix(), include)):
                continue

            if _is_binary_file(file_path):
                continue

            try:
                with file_path.open("r", encoding="utf-8", errors="replace") as handle:
                    for line_number, line in enumerate(handle, start=1):
                        if regex.search(line):
                            matches.append(
                                {
                                    "path": str(file_path),
                                    "line": line_number,
                                    "preview": line.strip()[:500],
                                }
                            )
                            if len(matches) >= max_results:
                                return matches
            except OSError:
                continue

    return matches


def _read_file(path: Path, offset: int, limit: int) -> str:
    if not path.is_file():
        raise RuntimeError(f"Path is not a file: {path}")

    if _is_binary_file(path):
        raise RuntimeError(f"Binary file cannot be read as text: {path}")

    lines: list[str] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_number, line in enumerate(handle, start=1):
            if line_number < offset:
                continue
            if len(lines) >= limit:
                break
            lines.append(f"{line_number}: {line.rstrip()}\n")

    return "".join(lines)


def _is_binary_file(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            chunk = handle.read(4096)
            return b"\x00" in chunk
    except OSError:
        return True


def _is_excluded(path: Path) -> bool:
    parts = set(path.parts)
    return any(part in DEFAULT_EXCLUDED_DIR_NAMES for part in parts)


def _write_file_text(path: Path, content: str, overwrite: bool, create_parent_dirs: bool) -> dict[str, object]:
    if path.exists() and path.is_dir():
        raise RuntimeError(f"Path is a directory, not a file: {path}")
    if path.exists() and not overwrite:
        raise RuntimeError(f"File already exists and overwrite is false: {path}")
    if create_parent_dirs:
        path.parent.mkdir(parents=True, exist_ok=True)
    elif not path.parent.exists():
        raise RuntimeError(f"Parent directory does not exist: {path.parent}")

    path.write_text(content, encoding="utf-8")
    return {
        "ok": True,
        "action": "write_file",
        "path": str(path),
        "bytes_written": len(content.encode("utf-8")),
    }


def _edit_file_text(path: Path, find_value: str, replace_value: str, replace_all: bool, require_match: bool) -> dict[str, object]:
    if not path.is_file():
        raise RuntimeError(f"Path is not a file: {path}")
    if _is_binary_file(path):
        raise RuntimeError(f"Binary file cannot be edited as text: {path}")

    text = path.read_text(encoding="utf-8", errors="replace")
    matches = text.count(find_value)
    if matches == 0 and require_match:
        raise RuntimeError("Edit failed: 'find' text did not match any content.")

    if replace_all:
        updated = text.replace(find_value, replace_value)
        replacements = matches
    else:
        updated = text.replace(find_value, replace_value, 1)
        replacements = 1 if matches > 0 else 0

    path.write_text(updated, encoding="utf-8")
    return {
        "ok": True,
        "action": "edit_file",
        "path": str(path),
        "replacements": replacements,
    }


def _copy_path(
    source_path: Path,
    destination_path: Path,
    overwrite: bool,
    recursive: bool,
    create_parent_dirs: bool,
) -> dict[str, object]:
    if not source_path.exists():
        raise RuntimeError(f"Source path does not exist: {source_path}")

    if create_parent_dirs:
        destination_path.parent.mkdir(parents=True, exist_ok=True)
    elif not destination_path.parent.exists():
        raise RuntimeError(f"Destination parent directory does not exist: {destination_path.parent}")

    if destination_path.exists():
        if not overwrite:
            raise RuntimeError(f"Destination already exists and overwrite is false: {destination_path}")
        if destination_path.is_dir():
            shutil.rmtree(destination_path)
        else:
            destination_path.unlink()

    if source_path.is_dir():
        if not recursive:
            raise RuntimeError("Source is a directory. Set recursive=true to copy folders.")
        shutil.copytree(source_path, destination_path)
        copied_type = "dir"
    else:
        shutil.copy2(source_path, destination_path)
        copied_type = "file"

    return {
        "ok": True,
        "action": "copy_path",
        "type": copied_type,
        "source_path": str(source_path),
        "destination_path": str(destination_path),
    }


def _move_path(source_path: Path, destination_path: Path, overwrite: bool, create_parent_dirs: bool) -> dict[str, object]:
    if not source_path.exists():
        raise RuntimeError(f"Source path does not exist: {source_path}")

    if create_parent_dirs:
        destination_path.parent.mkdir(parents=True, exist_ok=True)
    elif not destination_path.parent.exists():
        raise RuntimeError(f"Destination parent directory does not exist: {destination_path.parent}")

    if destination_path.exists():
        if not overwrite:
            raise RuntimeError(f"Destination already exists and overwrite is false: {destination_path}")
        if destination_path.is_dir():
            shutil.rmtree(destination_path)
        else:
            destination_path.unlink()

    moved = shutil.move(str(source_path), str(destination_path))
    return {
        "ok": True,
        "action": "move_path",
        "source_path": str(source_path),
        "destination_path": str(Path(moved)),
    }


def _delete_path(path: Path, confirm: bool, recursive: bool) -> dict[str, object]:
    if not confirm:
        raise RuntimeError("Delete blocked: set confirm=true to perform hard delete.")
    if not path.exists():
        raise RuntimeError(f"Path does not exist: {path}")

    target_type = "dir" if path.is_dir() else "file"
    if path.is_dir():
        if not recursive:
            raise RuntimeError("Path is a directory. Set recursive=true to delete folders.")
        shutil.rmtree(path)
    else:
        path.unlink()

    return {
        "ok": True,
        "action": "delete_path",
        "path": str(path),
        "type": target_type,
        "deleted": True,
    }


def _execute_command(command: str, workdir: Path, timeout_seconds: int) -> dict[str, object]:
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
            "action": "execute_command",
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
            "action": "execute_command",
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


def _required_string_like(arguments: dict[str, object], key: str) -> str:
    if key not in arguments:
        raise RuntimeError(f"Missing required argument '{key}'.")
    value = arguments.get(key)
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    raise RuntimeError(f"Argument '{key}' must be a string.")


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
