import asyncio
import fnmatch
import os
import re
from pathlib import Path

from app.config import BASE_DIR

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


class LocalFilesMCP(MCPPlugin):
    mcp_id = "local_files"
    display_name = "Local Files"
    description = "Searches files and directories on disk, reads file contents, and scans codebases."
    config_fields: list[McpConfigField] = []

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
        ]

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
            base_path = _resolve_base_path(_optional_str(arguments, "base_path", str(BASE_DIR)))
            max_results = _optional_int(arguments, "max_results", 500, 1, 5000)
            include_excluded = bool(arguments.get("include_excluded", False))
            results = await asyncio.to_thread(_glob_files, base_path, pattern, max_results, include_excluded)
            return {
                "base_path": str(base_path),
                "pattern": pattern,
                "results": results,
            }

        if tool_id == "search_content":
            pattern = _required_str(arguments, "pattern")
            base_path = _resolve_base_path(_optional_str(arguments, "base_path", str(BASE_DIR)))
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

        raise RuntimeError(f"Unsupported Local Files tool: {tool_id}")


def _resolve_base_path(raw_path: str) -> Path:
    path = Path(raw_path).expanduser().resolve()
    if not path.exists():
        raise RuntimeError(f"Path does not exist: {path}")
    return path


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
