"""Git and GitHub MCP plugin for repository operations inside workspace."""

import asyncio
import os
import re
import shutil
import subprocess
from pathlib import Path

from app.config import BASE_DIR

from .base import MCPPlugin, McpConfigField, McpToolSpec


DEFAULT_WORKSPACE_PATH = (BASE_DIR / "data" / "workspace").resolve()
SSH_PRIVATE_PARAM = "github_ssh_private_key"
SSH_PUBLIC_PARAM = "github_ssh_public_key"


class GitOpsMCP(MCPPlugin):
    mcp_id = "git_ops"
    display_name = "Git Operations"
    description = "Checkout repositories and run git/GitHub workflows inside Krill workspace."
    config_fields: list[McpConfigField] = []

    def tool_specs(self) -> list[McpToolSpec]:
        return [
            McpToolSpec(
                id="checkout_repo",
                label="Checkout Repository",
                description="Clones a repository into workspace using owner_repo naming.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "repo_url": {"type": "string", "minLength": 1},
                    },
                    "required": ["repo_url"],
                },
            ),
            McpToolSpec(
                id="list_repos",
                label="List Repositories",
                description="Lists repositories currently present in workspace.",
                input_schema={"type": "object", "properties": {}},
            ),
            McpToolSpec(
                id="repo_status",
                label="Repository Status",
                description="Shows git status for a workspace repository.",
                input_schema={
                    "type": "object",
                    "properties": {"repo_id": {"type": "string", "minLength": 1}},
                    "required": ["repo_id"],
                },
            ),
            McpToolSpec(
                id="checkout_branch",
                label="Checkout Branch",
                description="Checks out an existing branch or creates a new one.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "repo_id": {"type": "string", "minLength": 1},
                        "branch": {"type": "string", "minLength": 1},
                        "create": {"type": "boolean"},
                    },
                    "required": ["repo_id", "branch"],
                },
            ),
            McpToolSpec(
                id="commit",
                label="Commit",
                description="Stages everything and creates a commit.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "repo_id": {"type": "string", "minLength": 1},
                        "message": {"type": "string", "minLength": 1},
                    },
                    "required": ["repo_id", "message"],
                },
            ),
            McpToolSpec(
                id="pull",
                label="Pull",
                description="Pulls latest changes from remote branch.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "repo_id": {"type": "string", "minLength": 1},
                        "remote": {"type": "string"},
                        "branch": {"type": "string"},
                    },
                    "required": ["repo_id"],
                },
            ),
            McpToolSpec(
                id="push",
                label="Push",
                description="Pushes current or specified branch with safeguards.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "repo_id": {"type": "string", "minLength": 1},
                        "remote": {"type": "string"},
                        "branch": {"type": "string"},
                        "force": {"type": "boolean"},
                    },
                    "required": ["repo_id"],
                },
            ),
            McpToolSpec(
                id="create_pr",
                label="Create PR",
                description="Creates a GitHub pull request using gh CLI.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "repo_id": {"type": "string", "minLength": 1},
                        "title": {"type": "string", "minLength": 1},
                        "body": {"type": "string", "minLength": 1},
                        "base": {"type": "string"},
                    },
                    "required": ["repo_id", "title", "body"],
                },
            ),
        ]

    async def verify(self, params: dict[str, str]) -> tuple[bool, str]:
        workspace = _resolve_workspace_path()
        await asyncio.to_thread(workspace.mkdir, parents=True, exist_ok=True)

        try:
            missing = [name for name in ("git", "ssh", "ssh-keygen", "gh") if not shutil.which(name)]
            if missing:
                return False, f"Git MCP missing required binaries: {', '.join(missing)}"

            private_key, public_key = await ensure_ssh_keypair(params, workspace)
            env = _command_env(private_key)
            _, git_stdout, _ = await _run_command(["git", "--version"], workspace, env, 20)
            ok, detail = await verify_github_ssh_access(workspace, private_key)
            if not ok:
                return True, (
                    f"Git MCP partially verified. Workspace: {workspace}. {git_stdout.splitlines()[0]}. "
                    f"SSH not authenticated yet: {detail}"
                )
        except Exception as exc:
            return False, f"Git MCP verification failed: {exc}"

        key_preview = public_key[:32] + "..." if len(public_key) > 35 else public_key
        return True, f"Git MCP verified. Workspace: {workspace}. {git_stdout.splitlines()[0]}. SSH key: {key_preview}"

    async def call_tool(self, tool_id: str, arguments: dict[str, object], params: dict[str, str]) -> dict[str, object]:
        workspace = _resolve_workspace_path()
        await asyncio.to_thread(workspace.mkdir, parents=True, exist_ok=True)
        private_key = params.get(SSH_PRIVATE_PARAM, "")
        env = _command_env(private_key)

        if tool_id == "checkout_repo":
            repo_url = _required_str(arguments, "repo_url")
            repo_id = _derive_repo_id(repo_url)
            repo_path = workspace / repo_id

            if (repo_path / ".git").exists():
                return {
                    "repo_id": repo_id,
                    "path": str(repo_path),
                    "status": "already_exists",
                }

            await _run_command(["git", "clone", repo_url, str(repo_path)], workspace, env, 120)
            return {
                "repo_id": repo_id,
                "path": str(repo_path),
                "status": "cloned",
            }

        if tool_id == "list_repos":
            repos = _list_workspace_repos(workspace)
            return {
                "workspace": str(workspace),
                "repos": repos,
            }

        repo_id = _required_str(arguments, "repo_id")
        repo_path = _resolve_repo_path(workspace, repo_id)

        if tool_id == "repo_status":
            _, stdout, _ = await _run_command(["git", "status", "--short", "--branch"], repo_path, env, 40)
            return {
                "repo_id": repo_id,
                "status": stdout.strip(),
            }

        if tool_id == "checkout_branch":
            branch = _required_str(arguments, "branch")
            create = bool(arguments.get("create", False))
            cmd = ["git", "checkout", "-b", branch] if create else ["git", "checkout", branch]
            _, stdout, stderr = await _run_command(cmd, repo_path, env, 60)
            return {
                "repo_id": repo_id,
                "branch": branch,
                "created": create,
                "stdout": stdout.strip(),
                "stderr": stderr.strip(),
            }

        if tool_id == "commit":
            message = _required_str(arguments, "message")
            await _run_command(["git", "add", "."], repo_path, env, 60)
            _, stdout, stderr = await _run_command(["git", "commit", "-m", message], repo_path, env, 60)
            return {
                "repo_id": repo_id,
                "message": message,
                "stdout": stdout.strip(),
                "stderr": stderr.strip(),
            }

        if tool_id == "pull":
            remote = _optional_str(arguments, "remote", "origin")
            branch = _optional_str(arguments, "branch", "")
            cmd = ["git", "pull", remote]
            if branch:
                cmd.append(branch)
            _, stdout, stderr = await _run_command(cmd, repo_path, env, 90)
            return {
                "repo_id": repo_id,
                "remote": remote,
                "branch": branch,
                "stdout": stdout.strip(),
                "stderr": stderr.strip(),
            }

        if tool_id == "push":
            remote = _optional_str(arguments, "remote", "origin")
            branch = _optional_str(arguments, "branch", "")
            force = bool(arguments.get("force", False))

            if not branch:
                _, current_branch, _ = await _run_command(
                    ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                    repo_path,
                    env,
                    20,
                )
                branch = current_branch.strip()

            if force:
                raise RuntimeError("Force push is currently disabled.")

            cmd = ["git", "push", remote, branch]
            if force:
                cmd.append("--force-with-lease")

            _, stdout, stderr = await _run_command(cmd, repo_path, env, 90)
            return {
                "repo_id": repo_id,
                "remote": remote,
                "branch": branch,
                "force": force,
                "stdout": stdout.strip(),
                "stderr": stderr.strip(),
            }

        if tool_id == "create_pr":
            title = _required_str(arguments, "title")
            body = _required_str(arguments, "body")
            base = _optional_str(arguments, "base", "main")

            _, stdout, stderr = await _run_command(
                ["gh", "pr", "create", "--title", title, "--body", body, "--base", base],
                repo_path,
                env,
                120,
            )
            return {
                "repo_id": repo_id,
                "title": title,
                "base": base,
                "result": stdout.strip(),
                "stderr": stderr.strip(),
            }

        raise RuntimeError(f"Unsupported Git MCP tool: {tool_id}")


def _derive_repo_id(repo_url: str) -> str:
    normalized = repo_url.strip().rstrip("/")
    if normalized.endswith(".git"):
        normalized = normalized[:-4]

    match = re.search(r"[:/]([^/:]+)/([^/:]+)$", normalized)
    if not match:
        raise RuntimeError("Repository URL must include owner and repository name.")

    owner = match.group(1).strip().replace("-", "_")
    repo = match.group(2).strip().replace("-", "_")
    if not owner or not repo:
        raise RuntimeError("Could not derive owner_repo identifier from URL.")

    return f"{owner}_{repo}".lower()


def _resolve_workspace_path() -> Path:
    env_path = os.getenv("KRILL_WORKSPACE_PATH", "").strip()
    raw_path = env_path if env_path else str(DEFAULT_WORKSPACE_PATH)

    return Path(raw_path).resolve()


def get_workspace_path() -> Path:
    return _resolve_workspace_path()


def _resolve_repo_path(workspace: Path, repo_id: str) -> Path:
    clean_repo_id = repo_id.strip()
    if not clean_repo_id:
        raise RuntimeError("repo_id is required.")

    repo_path = (workspace / clean_repo_id).resolve()
    if workspace not in repo_path.parents and repo_path != workspace:
        raise RuntimeError("Repository path resolved outside workspace.")

    if not (repo_path / ".git").exists():
        raise RuntimeError(f"Repository '{clean_repo_id}' not found in workspace.")

    return repo_path


def _list_workspace_repos(workspace: Path) -> list[dict[str, str]]:
    repos: list[dict[str, str]] = []
    if not workspace.exists():
        return repos

    for entry in sorted(workspace.iterdir(), key=lambda item: item.name.lower()):
        if not entry.is_dir():
            continue
        if not (entry / ".git").exists():
            continue
        repos.append({"repo_id": entry.name, "path": str(entry)})

    return repos


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


def _command_env(private_key_content: str) -> dict[str, str]:
    env = dict(os.environ)
    if not private_key_content.strip():
        return env

    workspace = _resolve_workspace_path()
    private_key_path = _ssh_private_key_path(workspace)
    materialize_ssh_keypair(workspace, private_key_content, _read_public_key_if_exists(workspace))
    env["GIT_SSH_COMMAND"] = (
        f'ssh -i "{private_key_path}" -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new'
    )
    return env


def _ssh_dir(workspace: Path) -> Path:
    return (workspace / ".ssh").resolve()


def _ssh_private_key_path(workspace: Path) -> Path:
    return _ssh_dir(workspace) / "krill_ed25519"


def _ssh_public_key_path(workspace: Path) -> Path:
    return _ssh_dir(workspace) / "krill_ed25519.pub"


async def ensure_ssh_keypair(params: dict[str, str], workspace: Path) -> tuple[str, str]:
    return await asyncio.to_thread(_ensure_ssh_keypair_sync, params, workspace)


def _ensure_ssh_keypair_sync(params: dict[str, str], workspace: Path) -> tuple[str, str]:
    ssh_dir = _ssh_dir(workspace)
    ssh_dir.mkdir(parents=True, exist_ok=True)
    private_key = _ssh_private_key_path(workspace)
    public_key = _ssh_public_key_path(workspace)

    configured_private = params.get(SSH_PRIVATE_PARAM, "").strip()
    configured_public = params.get(SSH_PUBLIC_PARAM, "").strip()

    if configured_private and configured_public:
        materialize_ssh_keypair(workspace, configured_private, configured_public)
        return configured_private, configured_public

    if not private_key.exists() or not public_key.exists():
        subprocess.run(
            [
                "ssh-keygen",
                "-t",
                "ed25519",
                "-f",
                str(private_key),
                "-N",
                "",
                "-C",
                "krill-workspace",
            ],
            capture_output=True,
            text=True,
            timeout=40,
            check=True,
        )

    private_content = private_key.read_text(encoding="utf-8").strip()
    if not private_content:
        raise RuntimeError("SSH private key is empty.")

    public_content = public_key.read_text(encoding="utf-8").strip()
    if not public_content:
        raise RuntimeError("SSH public key is empty.")

    return private_content, public_content


async def get_or_create_ssh_public_key(params: dict[str, str], workspace: Path) -> tuple[str, str]:
    return await ensure_ssh_keypair(params, workspace)


def materialize_ssh_keypair(workspace: Path, private_key_content: str, public_key_content: str) -> None:
    ssh_dir = _ssh_dir(workspace)
    ssh_dir.mkdir(parents=True, exist_ok=True)
    private_key = _ssh_private_key_path(workspace)
    public_key = _ssh_public_key_path(workspace)

    private_payload = private_key_content.strip() + "\n"
    public_payload = public_key_content.strip() + "\n"

    if private_payload.strip():
        private_key.write_text(private_payload, encoding="utf-8")
        try:
            os.chmod(private_key, 0o600)
        except Exception:
            pass
    if public_payload.strip():
        public_key.write_text(public_payload, encoding="utf-8")


def _read_public_key_if_exists(workspace: Path) -> str:
    path = _ssh_public_key_path(workspace)
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


async def verify_github_ssh_access(workspace: Path, private_key_content: str) -> tuple[bool, str]:
    return await asyncio.to_thread(_verify_github_ssh_access_sync, workspace, private_key_content)


def _verify_github_ssh_access_sync(workspace: Path, private_key_content: str) -> tuple[bool, str]:
    private_key = _ssh_private_key_path(workspace)
    public_key = _ssh_public_key_path(workspace)
    if not private_key_content.strip():
        raise RuntimeError("SSH private key missing.")
    materialize_ssh_keypair(workspace, private_key_content, _read_public_key_if_exists(workspace))
    if not private_key.exists() or not public_key.exists():
        raise RuntimeError("SSH key files are missing.")

    cmd = [
        "ssh",
        "-i",
        str(private_key),
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-T",
        "git@github.com",
    ]
    completed = subprocess.run(
        cmd,
        cwd=str(workspace),
        capture_output=True,
        text=True,
        timeout=25,
        check=False,
    )

    combined = f"{completed.stdout}\n{completed.stderr}".strip()
    normalized = combined.lower()

    if "successfully authenticated" in normalized or "hi " in normalized:
        return True, combined or "GitHub SSH authentication successful."

    if completed.returncode in {0, 1} and ("authenticated" in normalized or "hi " in normalized):
        return True, combined or "GitHub SSH authentication successful."

    if "permission denied" in normalized:
        return False, "GitHub SSH authentication failed: permission denied. Add the key to your GitHub account."

    return False, f"GitHub SSH verification failed: {combined or 'No output.'}"


async def _run_command(command: list[str], cwd: Path, env: dict[str, str], timeout_seconds: int) -> tuple[int, str, str]:
    return await asyncio.to_thread(_run_command_sync, command, cwd, env, timeout_seconds)


def _run_command_sync(command: list[str], cwd: Path, env: dict[str, str], timeout_seconds: int) -> tuple[int, str, str]:
    completed = subprocess.run(
        command,
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )

    stdout = completed.stdout or ""
    stderr = completed.stderr or ""

    if completed.returncode != 0:
        detail = stderr.strip() or stdout.strip() or "Command failed without output."
        raise RuntimeError(f"{' '.join(command)} failed: {detail}")

    return completed.returncode, stdout, stderr
